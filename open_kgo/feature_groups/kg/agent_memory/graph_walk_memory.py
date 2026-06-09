"""NetworkX-backed graph-walk agent memory store.

Second concrete in the ``agent_memory`` family alongside ``NetworkxMemoryReader``
(lexical search). This reader implements ``retrieval_mode=graph`` — the pure
graph-walk retrieval branch the lexical concrete narrows away — by treating the
``query_text`` as a seed node id and returning the memories reachable from it
(BFS over the directed memory graph). It is the family's proof that the
``retrieval_mode`` enum's ``graph`` value is real, and it adds no new dependency
(NetworkX is already a family dependency).

Memory data is loaded from a JSON file at ``locator`` (shape:
``{user_id: {"nodes": [...], "edges": [...]}}``), the same shape the lexical
concrete consumes. ``retrieval_mode`` is narrowed to ``graph`` and
``pagination_style`` to ``none`` via ``SUPPORTED_VALUES``; ``retrieval_mode``
is additionally listed in ``REQUIRED_KEYS`` because the family default is
``lexical`` (a value this reader does not honor) and ``SUPPORTED_VALUES``
only checks keys present in the slot, so an omitted ``retrieval_mode`` would
otherwise validate and silently run graph retrieval under a defaulted
``lexical`` label.

The family-level bi-temporal keys (``valid_at_range`` / ``invalid_at_range`` /
``reference_time``) are ACCEPTED but NOT APPLIED by this graph-walk concrete:
the BFS returns reachable memories regardless of temporal validity. The lexical
sibling (``NetworkxMemoryReader``) honors ``valid_at_range``; this one does not
yet. This mirrors how the family base documents the ``memory_scope_*`` aliases
as accepted-but-no-op until a concrete owns the corresponding store.
"""

from __future__ import annotations

from collections import deque
from typing import Any, ClassVar, Mapping

import networkx as nx

from mloda.core.abstract_plugins.components.feature_set import FeatureSet

from open_kgo.feature_groups.kg.agent_memory.base import (
    AgentMemoryFeatureGroup,
    AgentMemoryReader,
)
from open_kgo.feature_groups.kg.errors import FixtureLoadError, UnknownMemoryScopeError
from open_kgo.feature_groups.kg.fixtures import load_json_fixture


def _validate_user_data(connector_id: str, locator: str, user_id: str, user_data: Any) -> Mapping[str, Any]:
    """Raise ``FixtureLoadError`` unless ``user_data`` matches the documented shape.

    Kept local to this concrete (rather than imported from the lexical reader's
    private module) so the two backends stay independent — the same
    self-contained pattern the other families follow.

    Beyond the top-level shape, every node must be an object carrying ``id``
    and every edge an object carrying ``src``/``tgt`` whose endpoints reference
    declared node ids. ``MultiDiGraph.add_edge`` auto-creates missing
    endpoints, so a dangling edge reference would otherwise materialize an
    attribute-less node whose BFS row is missing ``label``, silently violating
    the family row shape; missing ``id``/``src``/``tgt`` keys would surface as
    raw ``KeyError`` from the graph builder.
    """
    if not isinstance(user_data, dict):
        raise FixtureLoadError(
            connector_id, locator, f"entry for {user_id!r} must be an object, got {type(user_data).__name__}."
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


def _build_memory_graph(user_data: Mapping[str, Any]) -> nx.MultiDiGraph:
    """Build a directed memory graph from a single user's validated entry."""
    g: nx.MultiDiGraph = nx.MultiDiGraph()
    for node in user_data["nodes"]:
        g.add_node(node["id"], **{k: v for k, v in node.items() if k != "id"})
    for edge in user_data["edges"]:
        g.add_edge(edge["src"], edge["tgt"], **{k: v for k, v in edge.items() if k not in {"src", "tgt"}})
    return g


class GraphWalkMemoryReader(AgentMemoryReader):
    CONNECTOR_ID: ClassVar[str] = "graph_walk_memory"
    # retrieval_mode is REQUIRED (not just narrowed): the family default is
    # "lexical", which this reader does not honor, and SUPPORTED_VALUES only
    # validates keys present in the slot. An omitted retrieval_mode would
    # otherwise pass is_valid_credentials and silently run graph retrieval
    # under a defaulted "lexical" label.
    REQUIRED_KEYS: ClassVar[tuple[tuple[str, ...], ...]] = (
        ("locator",),
        ("memory_scope_user_id",),
        ("retrieval_mode",),
    )
    SUPPORTED_VALUES: ClassVar[Mapping[str, frozenset[Any]]] = {
        "pagination_style": frozenset({"none"}),
        "retrieval_mode": frozenset({"graph"}),
    }

    @classmethod
    def _connect_from_slot(cls, slot: Mapping[str, Any]) -> nx.MultiDiGraph:
        locator = str(slot["locator"])
        store = load_json_fixture(cls.CONNECTOR_ID, locator)
        user_id = str(slot["memory_scope_user_id"])
        if user_id not in store:
            raise UnknownMemoryScopeError(cls.CONNECTOR_ID, user_id)
        user_data = _validate_user_data(cls.CONNECTOR_ID, locator, user_id, store[user_id])
        return _build_memory_graph(user_data)

    @classmethod
    def build_query(cls, features: FeatureSet) -> str:
        feature = next(iter(features.features))
        text = feature.options.get("query_text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"{cls.CONNECTOR_ID}: 'query_text' (the seed node id) is required.")
        # Return the stripped seed: validation already requires non-whitespace
        # content, and an unstripped "  m1 " would validate here yet match no
        # node in the walk, silently returning [].
        return text.strip()

    @classmethod
    def load_data(cls, data_access: Any, features: FeatureSet) -> list[dict[str, Any]]:
        ctx = cls._prepare_load(data_access)
        graph = cls._connect_from_slot(ctx.slot)
        seed = cls.build_query(features)

        if seed not in graph:
            return []

        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        queue: deque[str] = deque([seed])
        # BFS over reachable memories; short-circuits at result_limit so the cap
        # bounds the walk rather than slicing a fully-expanded reachable set.
        while queue and len(rows) < ctx.result_limit:
            node_id = queue.popleft()
            if node_id in seen:
                continue
            seen.add(node_id)
            rows.append({"id": node_id, **graph.nodes[node_id]})
            queue.extend(successor for successor in graph.successors(node_id) if successor not in seen)
        return rows


class GraphWalkMemoryFeatureGroup(AgentMemoryFeatureGroup):
    READER_CLASS: ClassVar[type[GraphWalkMemoryReader]] = GraphWalkMemoryReader  # type: ignore[assignment]
