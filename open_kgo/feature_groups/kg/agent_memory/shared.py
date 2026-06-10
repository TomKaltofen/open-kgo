"""Fixture-shape validation and graph building shared by the agent_memory concretes.

Both concretes load the same fixture shape
(``{user_id: {"nodes": [...], "edges": [...]}}``) and used to carry local
copies of the shape validator and the MultiDiGraph builder. The copies have
been folded into this module; the one real difference between them survives
as the ``require_graph_integrity`` flag on ``validate_user_data``.
"""

from __future__ import annotations

from typing import Any, Mapping

import networkx as nx

from open_kgo.feature_groups.kg.errors import FixtureLoadError


def validate_user_data(
    connector_id: str,
    locator: str,
    user_id: str,
    user_data: Any,
    *,
    require_graph_integrity: bool = False,
) -> Mapping[str, Any]:
    """Raise ``FixtureLoadError`` unless ``user_data`` matches the documented shape.

    The top-level checks (object with ``nodes``/``edges`` lists) apply to every
    agent_memory concrete. ``require_graph_integrity=True`` additionally
    requires every node to be an object carrying ``id`` and every edge an
    object carrying ``src``/``tgt`` whose endpoints reference declared node
    ids. ``MultiDiGraph.add_edge`` auto-creates missing endpoints, so a
    dangling edge reference would otherwise materialize an attribute-less node
    whose BFS row is missing ``label``, silently violating the family row
    shape; missing ``id``/``src``/``tgt`` keys would surface as raw
    ``KeyError`` from the graph builder. The graph-walk concrete requires this
    (its rows come straight from the walk); the lexical concrete keeps the
    historical lenient shape gate.
    """
    if not isinstance(user_data, dict):
        raise FixtureLoadError(
            connector_id,
            locator,
            f"entry for {user_id!r} must be an object, got {type(user_data).__name__}.",
        )
    for key in ("nodes", "edges"):
        if key not in user_data:
            raise FixtureLoadError(connector_id, locator, f"entry for {user_id!r} is missing required key {key!r}.")
        if not isinstance(user_data[key], list):
            raise FixtureLoadError(
                connector_id,
                locator,
                f"entry for {user_id!r} key {key!r} must be a list, got {type(user_data[key]).__name__}.",
            )
    if not require_graph_integrity:
        return user_data
    node_ids: set[Any] = set()
    for index, node in enumerate(user_data["nodes"]):
        if not isinstance(node, dict) or "id" not in node:
            raise FixtureLoadError(
                connector_id,
                locator,
                f"entry for {user_id!r} nodes[{index}] must be an object with an 'id' key, got {node!r}.",
            )
        node_ids.add(node["id"])
    for index, edge in enumerate(user_data["edges"]):
        if not isinstance(edge, dict) or "src" not in edge or "tgt" not in edge:
            raise FixtureLoadError(
                connector_id,
                locator,
                f"entry for {user_id!r} edges[{index}] must be an object with 'src' and 'tgt' keys, got {edge!r}.",
            )
        for endpoint in ("src", "tgt"):
            if edge[endpoint] not in node_ids:
                raise FixtureLoadError(
                    connector_id,
                    locator,
                    f"entry for {user_id!r} edges[{index}] {endpoint}={edge[endpoint]!r} references no declared "
                    f"node id (dangling edge endpoints would materialize attribute-less rows).",
                )
    return user_data


def build_memory_graph(user_data: Mapping[str, Any]) -> nx.MultiDiGraph:
    """Build a directed memory graph from a single user's already-validated entry.

    ``user_data`` is the inner ``{"nodes": [...], "edges": [...]}`` object;
    shape validation lives in ``validate_user_data`` so this builder can use
    direct subscript access (no ``.get(..., [])`` silent fallbacks).
    """
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    for node in user_data["nodes"]:
        g.add_node(node["id"], **{k: v for k, v in node.items() if k != "id"})
    for edge in user_data["edges"]:
        g.add_edge(edge["src"], edge["tgt"], **{k: v for k, v in edge.items() if k not in {"src", "tgt"}})
    return g
