"""Shared library for the demo evaluation notebooks.

The three eval notebooks (``eval_qa_accuracy.py``, ``eval_qa_accuracy_2hop.py``,
``eval_arch1_vs_arch2.py``) used to carry near-identical copies of the setup
(ensure_data + ontology load + GML read), the two traversal architectures, the
QA-file loader, and the per-question accumulation / markdown-table loop. The
shared pieces live here; each notebook keeps only what is specific to it (its
question parser and its hop-chaining strategy), so the notebooks stay readable
as demos while the eval semantics cannot drift between them.

Architecture vocabulary (shared by all three notebooks):

- **Architecture 1** (``arch1_hop``): plain traversal, follow any edge matching
  the relation name. No errors, no guarantees.
- **Architecture 2** (``arch2_hop``): ontology-guided traversal. The source
  entity type is validated against the ontology before the hop and the range
  type is checked on arrival; violations raise ``ValueError`` immediately
  instead of returning empty.
- ``rev_hop`` is the unchecked reverse lookup both architectures share (no
  source-type constraint applies to a reverse hop).
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import networkx as nx

from open_kgo.feature_groups.kg.ontology.registry import OntologyRegistry

DEMO_DIR = Path(__file__).resolve().parent
DATA_DIR = DEMO_DIR / "data"
REPO_ROOT = DEMO_DIR.parent

_ONTOLOGY_FIXTURES = REPO_ROOT / "open_kgo" / "feature_groups" / "kg" / "ontology" / "tests" / "fixtures"
ONTOLOGY_YAML = _ONTOLOGY_FIXTURES / "metaqa_ontology.yaml"
TINY_GML = _ONTOLOGY_FIXTURES / "metaqa_tiny.gml"
GML_FILE = DATA_DIR / "metaqa_sample.gml"
QA_1HOP = DATA_DIR / "sample_qa.txt"
QA_2HOP = DATA_DIR / "sample_qa_2hop.txt"


def load_sample_graph() -> "nx.MultiDiGraph":
    """Build the sample data if needed, load the ontology, and return the sample graph.

    The shared setup prologue of every eval notebook: ``demo.data.ensure_data``
    builds the committed sample subgraph offline, the MetaQA ontology fixture is
    (re)loaded into a clean ``OntologyRegistry``, and the QA-anchored GML sample
    is read into a ``MultiDiGraph``.
    """
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from demo.data import ensure_data

    ensure_data()
    OntologyRegistry._clear()
    OntologyRegistry.load_file(str(ONTOLOGY_YAML))
    graph: nx.MultiDiGraph = nx.read_gml(str(GML_FILE))
    return graph


def arch1_hop(g: "nx.MultiDiGraph", start: str, relation: str) -> set[str]:
    """Architecture 1 forward hop: follow any edge matching relation. No type checking."""
    if start not in g:
        return set()
    return {t for _, t, d in g.out_edges(start, data=True) if d.get("relation") == relation}


def arch2_hop(g: "nx.MultiDiGraph", start: str, relation: str, namespace: str = "movie") -> set[str]:
    """Architecture 2 forward hop: ontology-validated domain + range; raises ``ValueError`` on violation."""
    entity_type = g.nodes[start].get("type", "Unknown")
    if not OntologyRegistry.is_valid_edge(namespace, entity_type, relation):
        raise ValueError(
            f"Ontology violation: '{relation}' is not valid from entity type '{entity_type}' "
            f"in namespace '{namespace}'."
        )
    expected_range = OntologyRegistry.get_range_type(namespace, relation)
    seen: set[str] = set()
    for _, t, d in g.out_edges(start, data=True):
        if d.get("relation") != relation:
            continue
        if expected_range is not None:
            target_type = g.nodes[t].get("type", "Unknown")
            if target_type != expected_range:
                raise ValueError(
                    f"Range violation: '{relation}' expects range '{expected_range}' "
                    f"but reached node '{t}' of type '{target_type}'."
                )
        seen.add(t)
    return seen


def rev_hop(g: "nx.MultiDiGraph", target: str, relation: str) -> set[str]:
    """Reverse hop shared by both architectures: all nodes pointing to ``target`` via ``relation``."""
    return {s for s, t, d in g.in_edges(target, data=True) if d.get("relation") == relation}


def load_qa(path: Path) -> list[tuple[str, set[str]]]:
    """Load (question, gold_answer_set) pairs from a MetaQA QA file."""
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) != 2:
                continue
            q, raw_answers = parts
            rows.append((q, {a.strip() for a in raw_answers.split("|")}))
    return rows


def graph_type_rows_md(graph: "nx.MultiDiGraph") -> str:
    """Markdown table rows of ``| entity type | count |`` for the graph-info cells."""
    types: dict[str, int] = {}
    for _, d in graph.nodes(data=True):
        t = d.get("type", "Unknown")
        types[t] = types.get(t, 0) + 1
    return "\n".join(f"| {t} | {c} |" for t, c in sorted(types.items()))


# evaluate_question(question, entity, entity_type) -> None to skip, or
# (key, answers_arch1, answers_arch2, arch2_blocked_count).
EvaluateQuestion = Callable[[str, str, str], "tuple[str, set[str], set[str], int] | None"]


@dataclass
class QaEvalResult:
    """Accumulated outcome of one QA eval run, plus the shared report builders."""

    arch1: dict[str, list[int]]  # key -> [hits, total]
    arch2: dict[str, list[int]]
    n_questions: int
    skipped: int
    disagreements: int
    arch2_blocked: int

    @property
    def evaluated(self) -> int:
        return sum(n for _, n in self.arch1.values())

    def _totals(self) -> tuple[int, int, int]:
        total_a1 = sum(h for h, _ in self.arch1.values())
        total_a2 = sum(h for h, _ in self.arch2.values())
        return total_a1, total_a2, self.evaluated

    @staticmethod
    def _pct(hits: int, total: int) -> str:
        return f"{100 * hits // total}%" if total else "n/a"

    def rows_md(self) -> str:
        """Per-key markdown rows for the results table, plus the bold TOTAL row."""
        rows = ""
        for key in sorted(set(self.arch1) | set(self.arch2)):
            h1, n1 = self.arch1[key]
            h2, n2 = self.arch2[key]
            diff = "**DIFF**" if h1 != h2 else ""
            rows += f"| `{key}` | {n1} | {h1} ({self._pct(h1, n1)}) | {h2} ({self._pct(h2, n2)}) | {diff} |\n"
        total_a1, total_a2, total = self._totals()
        rows += f"| **TOTAL** | **{total}** | **{self._pct(total_a1, total)}** | **{self._pct(total_a2, total)}** | |"
        return rows


def evaluate_qa(
    qa: list[tuple[str, set[str]]],
    graph: "nx.MultiDiGraph",
    evaluate_question: EvaluateQuestion,
) -> QaEvalResult:
    """Run the shared per-question accumulation loop.

    Handles the parts every eval notebook repeated: the ``[entity]`` extraction,
    the entity-in-graph check, hit accounting per key, the disagreement counter,
    and the arch2 blocked tally. ``evaluate_question`` supplies the
    notebook-specific part: classify the question and run both architectures,
    returning ``(key, answers_arch1, answers_arch2, blocked)`` or ``None`` to
    skip an unclassifiable question.
    """
    a1: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    a2: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    skipped = 0
    blocked_total = 0
    disagreements = 0

    for question, gold in qa:
        m = re.search(r"\[(.+?)\]", question)
        if not m:
            skipped += 1
            continue
        entity = m.group(1)
        if entity not in graph:
            skipped += 1
            continue
        entity_type: Any = graph.nodes[entity].get("type", "Unknown")
        outcome = evaluate_question(question, entity, entity_type)
        if outcome is None:
            skipped += 1
            continue
        key, answers1, answers2, blocked = outcome
        blocked_total += blocked

        hit1 = bool(answers1 & gold)
        a1[key][0] += int(hit1)
        a1[key][1] += 1

        hit2 = bool(answers2 & gold)
        a2[key][0] += int(hit2)
        a2[key][1] += 1

        if hit1 != hit2:
            disagreements += 1

    return QaEvalResult(
        arch1=dict(a1),
        arch2=dict(a2),
        n_questions=len(qa),
        skipped=skipped,
        disagreements=disagreements,
        arch2_blocked=blocked_total,
    )
