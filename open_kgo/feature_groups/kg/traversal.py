"""Shared bounded BFS helpers for KG connector readers.

Six concretes walk a graph breadth-first under a ``result_limit`` budget and
used to carry their own copies of the loop (dbt manifest, OpenLineage events,
SPDX SBOM, both citation_rest concretes, and the graph-walk memory reader).
The copies agreed on the load-bearing invariants (visited-set cycle
termination, "the limit bounds the work walked, not just the output sliced")
but differed in row factories, neighbor sources, and dedup scope, which made
the agreement easy to break by editing one copy. The two skeletons now live
here; concretes keep thin wrappers that bind their edge maps and row shapes.

Two shapes are provided:

- ``bfs_frontier_walk``: the directional lineage/dependency walk (dbt,
  OpenLineage, SPDX). Walks ``depth`` frontier generations from ``start``,
  emitting a row per newly-reached node, with traversal and emission
  deduplicated separately: a local ``visited`` set terminates cycles per
  walk, while the caller-owned ``emitted`` set spans walks so a
  ``direction=BOTH`` pair of calls emits an overlap node once (and bills the
  budget once) yet still expands it in the second direction.
- ``bfs_collect_ids``: the hop-tagged reachability walk (citation_rest,
  agent_memory graph walk). Collects node ids out to ``depth`` hops
  (``None`` = unbounded), optionally stopping after ``max_nodes`` ids.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Callable, Iterable


def bfs_frontier_walk(
    neighbors: Callable[[str], Iterable[str]],
    start: str,
    *,
    depth: int,
    remaining: int,
    emit: Callable[[str], dict[str, Any]],
    emitted: set[str] | None = None,
    should_traverse: Callable[[str], bool] | None = None,
) -> list[dict[str, Any]]:
    """BFS ``depth`` frontier generations from ``start``; emit a row per newly-reached node.

    Aborts as soon as ``remaining`` NEW rows have been emitted so the caller's
    ``result_limit`` bounds the work walked, not just the output sliced;
    without this guard a wide graph pays full BFS cost for a tiny limit.
    ``start`` itself is never emitted (callers emit their start row before
    walking).

    ``emitted``, when given, is caller-owned and mutated in place: a
    ``direction=BOTH`` caller passes ONE set (seeded with the start node) to
    both directional walks so a node reachable in both directions (a cycle
    through the start) is emitted once and bills the budget once. An
    already-emitted overlap node is still EXPANDED by the second walk (it
    costs no budget), so nodes reachable in the second direction only through
    it are not dropped. ``emitted=None`` builds a fresh set seeded with
    ``start`` (single-direction semantics, used by direct unit-test callers).

    ``should_traverse``, when given, gates dangling nodes: a neighbour it
    rejects is neither emitted NOR expanded, so a real node reachable only
    THROUGH a missing intermediate stays unreachable (the SPDX "dangling
    edges skipped" contract covers transit nodes too).
    """
    if depth <= 0 or remaining <= 0:
        return []
    if emitted is None:
        emitted = {start}
    visited: set[str] = {start}
    out: list[dict[str, Any]] = []
    frontier: list[str] = [start]
    for _ in range(depth):
        next_frontier: list[str] = []
        for node in frontier:
            for neighbour in neighbors(node):
                if neighbour in visited:
                    continue
                visited.add(neighbour)
                if should_traverse is not None and not should_traverse(neighbour):
                    continue
                next_frontier.append(neighbour)
                if neighbour in emitted:
                    continue
                emitted.add(neighbour)
                out.append(emit(neighbour))
                if len(out) >= remaining:
                    return out
        if not next_frontier:
            break
        frontier = next_frontier
    return out


def bfs_collect_ids(
    contains: Callable[[str], bool],
    neighbors: Callable[[str], Iterable[str]],
    start: str,
    *,
    depth: int | None = None,
    max_nodes: int | None = None,
) -> list[str]:
    """Collect the node ids reachable from ``start`` out to ``depth`` hops, ``start`` included.

    Nodes failing ``contains`` (absent from the backing catalog/graph) are
    skipped and not expanded; that covers a ``start`` that does not exist (an
    empty result, not an error). ``depth=None`` walks without a hop bound.
    ``max_nodes``, when given, stops the walk as soon as that many ids have
    been collected so the cap bounds the walk rather than slicing a
    fully-expanded reachable set.
    """
    collected: list[str] = []
    visited: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(start, 0)])
    while queue:
        if max_nodes is not None and len(collected) >= max_nodes:
            break
        node_id, hop = queue.popleft()
        if node_id in visited or not contains(node_id):
            continue
        visited.add(node_id)
        collected.append(node_id)
        if depth is None or hop < depth:
            for neighbour in neighbors(node_id):
                if neighbour not in visited:
                    queue.append((neighbour, hop + 1))
    return collected
