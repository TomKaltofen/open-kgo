import marimo

__generated_with = "0.23.4"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def title(mo):
    mo.md("""
    # 2-hop QA Accuracy: Arch 1 vs Arch 2

    Measures answer accuracy on the committed 2-hop sample QA set
    (`demo/data/sample_qa_2hop.txt`), a small hand-authored set of public movie
    facts in MetaQA's triple format.

    **Architecture 1:** plain traversal — follow any matching edge, no type checking.
    **Architecture 2:** ontology-guided — entity type validated before each forward hop,
    range type validated on arrival. Reverse hops are unchecked in both architectures.

    2-hop questions chain two relations through the movie KB. Two structural patterns:

    - **Non-Movie start:** `[Person/Genre/Year/Tag] <-(rev rel1)- Movies -(fwd rel2)-> Answer`
    - **Movie start (same-X):** `[Movie] -(fwd rel1)-> Entity <-(rev rel1)- Other Movies`

    Metric: **hit rate** — question answered correctly if the returned set contains
    at least one gold answer.

    **What this eval shows (and does not).** The shipped sample is *type-clean*: every
    edge already respects the ontology's domain/range, so Arch 2's per-hop validation
    never has a wrong-typed hop to block. The takeaway is therefore "ontology guidance
    **preserves** accuracy while adding per-hop type validation," not "ontology guidance
    **raises** accuracy" — this sample cannot demonstrate the latter, because there is no
    type-violating hop for Arch 2 to reject that Arch 1 would have followed. To see Arch 2
    block a wrong hop, the sample would need adversarial type-dirty edges.

    The hit rates below also depend on the heuristic question parser `infer_2hop_chain`,
    which maps each question to a relation chain by keyword matching against the known
    sample phrasings. A question it cannot classify is skipped, not scored, so the numbers
    reflect parser coverage and traversal correctness together, not traversal quality alone.

    The hop primitives, QA loader, and scoring loop are shared with the other eval
    notebooks via `demo/qa_eval_lib.py`; this notebook contributes the 2-hop
    question parser and the hop-chaining strategy.
    """)
    return


@app.cell
def _():
    import sys
    from pathlib import Path

    DEMO_DIR = Path(__file__).parent
    _ROOT = DEMO_DIR.parent
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    from demo import qa_eval_lib as lib

    graph = lib.load_sample_graph()

    return graph, lib


@app.cell
def graph_info(graph, lib, mo):
    mo.md(f"""
    **QA-anchored subgraph:** {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges

    Built by `demo/data/build_sample.py` as the 1-hop induced subgraph around
    every QA topic entity. All 10 movies are 1-hop topics in the 1-hop QA set,
    so the subgraph covers the full KB and all 2-hop answers are reachable.

    | Entity type | Count |
    |---|---|
    {lib.graph_type_rows_md(graph)}
    """)
    return


@app.cell
def _(lib):
    # ---------------------------------------------------------------------------
    # 2-hop traversal over the shared hop primitives
    # ---------------------------------------------------------------------------

    def traverse_2hop_arch1(g, entity: str, rel1: str, dir1: str, rel2: str, dir2: str) -> set[str]:
        """Chain two hops — no ontology checking."""
        if dir1 == "forward":
            intermediates = lib.arch1_hop(g, entity, rel1)
        else:
            intermediates = lib.rev_hop(g, entity, rel1)

        answers: set[str] = set()
        for mid in intermediates:
            if mid not in g:
                continue
            if dir2 == "forward":
                answers |= lib.arch1_hop(g, mid, rel2)
            else:
                answers |= lib.rev_hop(g, mid, rel2)
        return answers

    def traverse_2hop_arch2(g, entity: str, rel1: str, dir1: str, rel2: str, dir2: str) -> tuple[set[str], int]:
        """Chain two hops — ontology-validated on forward hops.

        Returns (answer_set, n_blocked) where n_blocked counts forward hops
        that raised a ValueError.
        """
        blocked = 0

        if dir1 == "forward":
            try:
                intermediates = lib.arch2_hop(g, entity, rel1)
            except ValueError:
                return set(), 1
        else:
            intermediates = lib.rev_hop(g, entity, rel1)

        answers: set[str] = set()
        for mid in intermediates:
            if mid not in g:
                continue
            if dir2 == "forward":
                try:
                    answers |= lib.arch2_hop(g, mid, rel2)
                except ValueError:
                    blocked += 1
            else:
                answers |= lib.rev_hop(g, mid, rel2)

        return answers, blocked

    return traverse_2hop_arch1, traverse_2hop_arch2


@app.cell
def _():
    # ---------------------------------------------------------------------------
    # 2-hop question parser
    # Returns (rel1, dir1, rel2, dir2) or None
    # ---------------------------------------------------------------------------

    def infer_2hop_chain(question: str, entity_type: str) -> tuple[str, str, str, str] | None:
        """Map a question to a ``(rel1, dir1, rel2, dir2)`` chain, or ``None`` if unrecognised.

        Heuristic, NOT a parser of general questions: it keyword-matches against the
        specific phrasings used in the committed sample QA set. Questions it cannot
        classify return ``None`` and are skipped (not scored), so the reported hit
        rates measure parser coverage and traversal correctness together. A real
        deployment would replace this with a learned or grammar-based question parser;
        it lives here only to drive the offline accuracy comparison reproducibly.
        """
        q = question.lower()

        # Movie-start: fwd(rel1) -> Entity <- rev(rel1) <- Other Movies
        if entity_type == "Movie":
            if any(
                k in q
                for k in ["same director", "also directed", "director of", "directed by the same", "share a director"]
            ):
                return ("directed_by", "forward", "directed_by", "reverse")
            if any(
                k in q
                for k in [
                    "same actor",
                    "share the same actor",
                    "have the same actor",
                    "same movie with",
                    "co-star",
                    "actor of",
                    "actor in",
                    "also starred in",
                    "also appears in",
                ]
            ):
                return ("starred_actors", "forward", "starred_actors", "reverse")
            if any(
                k in q
                for k in [
                    "same screenwriter",
                    "same writer",
                    "same screenplay",
                    "have the same screenwriter",
                    "same screenplay writer",
                    "scriptwriter",
                    "screenwriter of",
                    "screenwriter with",
                    "share the screenwriter",
                ]
            ):
                return ("written_by", "forward", "written_by", "reverse")
            return None

        # Non-Movie start: Entity <- rev(rel1) <- Movies -> fwd(rel2) -> Answer

        # Determine rel1 (the entity's role w.r.t. movies)
        if entity_type == "Person":
            if any(
                k in q
                for k in [
                    "directed by",
                    "films directed",
                    "movies directed",
                    "the director",
                    "co-direct",
                    "director of",
                ]
            ):
                rel1 = "directed_by"
            elif any(
                k in q
                for k in [
                    "written by",
                    "films written",
                    "movies written",
                    "screenwriter",
                    "co-wrote",
                    "co-writers",
                    "co-written",
                    "wrote",
                    "written films",
                ]
            ):
                rel1 = "written_by"
            else:
                rel1 = "starred_actors"
        elif entity_type == "Genre":
            rel1 = "has_genre"
        elif entity_type == "Language":
            rel1 = "in_language"
        elif entity_type == "Year":
            rel1 = "release_year"
        elif entity_type == "Tag":
            rel1 = "has_tags"
        else:
            return None

        # Determine rel2 (the answer type)
        if any(k in q for k in ["directed", "director", "co-director", "co-directed"]):
            rel2 = "directed_by"
        elif any(
            k in q
            for k in [
                "actors",
                "acted",
                "starred",
                "appeared in the same",
                "acted together",
                "who starred",
                "acted by",
                "co-star",
            ]
        ):
            rel2 = "starred_actors"
        elif any(k in q for k in ["written by", "wrote", "screenwriter", "co-writ", "co-writer"]):
            rel2 = "written_by"
        elif any(k in q for k in ["genre", "types", "kind", "sort", "fall under"]):
            rel2 = "has_genre"
        elif any(k in q for k in ["language"]):
            rel2 = "in_language"
        elif any(
            k in q
            for k in [
                "release year",
                "release date",
                "when were",
                "when was",
                "released in which year",
                "release dates",
                "release years",
            ]
        ):
            rel2 = "release_year"
        elif any(k in q for k in ["tags", "topics", "about", "applicable", "terms", "words"]):
            rel2 = "has_tags"
        else:
            return None

        return (rel1, "reverse", rel2, "forward")

    return (infer_2hop_chain,)


@app.cell
def run_eval(graph, infer_2hop_chain, lib, mo, traverse_2hop_arch1, traverse_2hop_arch2):
    _qa = lib.load_qa(lib.QA_2HOP)

    def _evaluate(question: str, entity: str, entity_type: str):
        """Classify the question into a chain, then run both 2-hop traversals."""
        _chain = infer_2hop_chain(question, entity_type)
        if _chain is None:
            return None
        _rel1, _dir1, _rel2, _dir2 = _chain
        _chain_key = f"{_rel1}({_dir1[:3]}) -> {_rel2}({_dir2[:3]})"
        _r1 = traverse_2hop_arch1(graph, entity, _rel1, _dir1, _rel2, _dir2)
        _r2, _blocked = traverse_2hop_arch2(graph, entity, _rel1, _dir1, _rel2, _dir2)
        return _chain_key, _r1, _r2, _blocked

    _result = lib.evaluate_qa(_qa, graph, _evaluate)

    mo.md(f"""
    ## Results

    **Test questions:** {_result.n_questions} total — {_result.evaluated} evaluated, {_result.skipped} skipped
    (skipped = entity not in graph or question template not recognised)

    | Chain | Questions | Arch 1 hit rate | Arch 2 hit rate | |
    |---|---|---|---|---|
    {_result.rows_md()}

    **Disagreements (arch1 hit ≠ arch2 hit):** {_result.disagreements}
    **Arch 2 forward-hop blocks across all hops:** {_result.arch2_blocked}

    > Hit rate = % of questions where at least one gold answer is in the returned set.
    > Reverse hops use the same traversal in both architectures (no source-type constraint applies).
    > Forward hops in Arch 2 are validated: domain entity type + range type checked per hop.
    > On this type-clean sample the two architectures are expected to **agree**: every hop is
    > already well-typed, so Arch 2's validation has nothing to block and accuracy is preserved,
    > not improved. A measured Arch 2 win would require adversarial type-dirty edges (absent here).
    > These hit rates also reflect `infer_2hop_chain` parser coverage, not traversal quality alone.
    """)
    return


if __name__ == "__main__":
    app.run()
