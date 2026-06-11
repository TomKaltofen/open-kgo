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
    # 1-hop QA Accuracy: Arch 1 vs Arch 2

    Measures answer accuracy on the committed sample QA set (`demo/data/sample_qa.txt`),
    a small hand-authored set of public movie facts in MetaQA's triple format.

    **Architecture 1:** plain traversal — follow any matching edge, no type checking.
    **Architecture 2:** ontology-guided — entity type validated before each hop,
    range type validated on arrival.

    Questions cover the 7 movie relations in two directions:
    - **Forward** (entity in brackets is a Movie): `Movie → relation → ?`
    - **Reverse** (entity is Person/Tag/Genre): find all Movies with that entity as target

    Metric: **hit rate** — question answered correctly if the returned set contains
    at least one gold answer.

    The traversal architectures, QA loader, and scoring loop are shared with the
    other eval notebooks via `demo/qa_eval_lib.py`; this notebook contributes the
    1-hop question parser and the per-question evaluation strategy.
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
    every QA topic entity. Sufficient for 1-hop accuracy: every topic and its
    1-hop neighbors (i.e. the answer space) are present.

    | Entity type | Count |
    |---|---|
    {lib.graph_type_rows_md(graph)}
    """)
    return


@app.cell
def _():
    # ---------------------------------------------------------------------------
    # Question parser
    # ---------------------------------------------------------------------------

    def infer_relation(question: str, entity_type: str) -> tuple[str, str] | None:
        """Return (relation, direction) for a question, or None if unclassifiable.

        direction is 'forward'  (Movie → relation → answer) or
                     'reverse'  (answer Movie → relation → entity).
        """
        q = question.lower()

        if entity_type == "Movie":
            # Forward: given Movie, follow relation outward
            if any(
                k in q
                for k in [
                    "director",
                    "directed by",
                    "who directed",
                    "who is the director",
                    "directed on",
                    "which person directed",
                ]
            ):
                return ("directed_by", "forward")
            if any(
                k in q
                for k in [
                    "who starred",
                    "who acted",
                    "who acts",
                    "who are the actors",
                    "starred which",
                    "starred who",
                    "who stars in",
                ]
            ):
                return ("starred_actors", "forward")
            if any(
                k in q
                for k in [
                    "who wrote",
                    "writer",
                    "written by",
                    "who is the author",
                    "screenplay",
                    "script",
                    "who is the creator",
                    "who in the world wrote",
                    "which person wrote",
                ]
            ):
                return ("written_by", "forward")
            if any(k in q for k in ["year", "release", "when was", "date"]):
                return ("release_year", "forward")
            if any(
                k in q
                for k in ["genre", "kind of", "type of", "sort of", "what kind", "what type", "what sort", "film genre"]
            ):
                return ("has_genre", "forward")
            if any(k in q for k in ["language"]):
                return ("in_language", "forward")
            if any(k in q for k in ["describe", "words", "topics", "terms", "about", "applicable"]):
                return ("has_tags", "forward")

        elif entity_type == "Person":
            # Reverse: given Person, find Movies pointing to them
            if any(k in q for k in ["direct", "director"]):
                return ("directed_by", "reverse")
            if any(k in q for k in ["writ", "author", "screenplay", "script", "story", "creator of the film script"]):
                return ("written_by", "reverse")
            # Default for Person is acting
            return ("starred_actors", "reverse")

        elif entity_type == "Tag":
            return ("has_tags", "reverse")

        elif entity_type == "Genre":
            return ("has_genre", "reverse")

        elif entity_type == "Language":
            return ("in_language", "reverse")

        elif entity_type == "Year":
            return ("release_year", "reverse")

        return None

    return (infer_relation,)


@app.cell
def run_eval(graph, infer_relation, lib, mo):
    _qa = lib.load_qa(lib.QA_1HOP)

    def _evaluate(question: str, entity: str, entity_type: str):
        """Classify the question, then run both architectures on the single hop.

        Reverse traversal uses the same unchecked hop for both architectures
        (no source entity type constraint applies to reverse lookup).
        """
        _parsed = infer_relation(question, entity_type)
        if _parsed is None:
            return None
        _rel, _direction = _parsed
        if _direction == "forward":
            _r1 = lib.arch1_hop(graph, entity, _rel)
            try:
                _r2 = lib.arch2_hop(graph, entity, _rel)
                _blocked = 0
            except ValueError:
                _r2 = set()
                _blocked = 1
        else:
            _r1 = lib.rev_hop(graph, entity, _rel)
            _r2 = set(_r1)
            _blocked = 0
        return _rel, _r1, _r2, _blocked

    _result = lib.evaluate_qa(_qa, graph, _evaluate)

    mo.md(f"""
    ## Results

    **Test questions:** {_result.n_questions} total — {_result.evaluated} evaluated, {_result.skipped} skipped
    (skipped = entity not in graph or question template not recognised)

    | Relation | Questions | Arch 1 hit rate | Arch 2 hit rate | |
    |---|---|---|---|---|
    {_result.rows_md()}

    **Disagreements (arch1 hit ≠ arch2 hit):** {_result.disagreements}
    **Arch 2 unexpected blocks on valid forward queries:** {_result.arch2_blocked}

    > Hit rate = % of questions where at least one gold answer is in the returned set.
    > Reverse-direction questions use the same traversal for both architectures
    > (no source entity type constraint applies to reverse lookup).
    """)
    return


if __name__ == "__main__":
    app.run()
