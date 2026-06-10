"""Family base for embedded / in-memory graph connectors."""

from __future__ import annotations

from typing import Any, ClassVar

from mloda.core.abstract_plugins.components.default_options_key import DefaultOptionKeys

from open_kgo.feature_groups.kg.base import (
    KgConnectorFeatureGroupBase,
    ParamReader,
    compose_property_mapping,
)


_GRAPH_FILE_FORMATS: dict[str, str] = {
    "gml": "Graph Modeling Language.",
    "graphml": "GraphML XML.",
    "edgelist": "Plain edge list.",
}


_OPERATIONS: dict[str, str] = {
    "nodes": "Return all node ids.",
    "edges": "Return all edges as [u, v] pairs.",
    "neighbors": "Return neighbors of `start_node`.",
}


class UnknownStartNodeError(ValueError):
    """Raised by embedded connectors when ``start_node`` is not present in the loaded graph.

    Shaped like ``UnknownTenantError`` / ``UnknownMemoryScopeError`` in
    ``kg.errors``: per-call validation can enforce that ``start_node`` is
    *present* for ``operation=neighbors``, but cannot enforce that the value
    *exists* in a given graph file, so the concrete reader resolves it at
    runtime and raises this typed error. Every embedded concrete MUST raise
    this same error on an unknown ``start_node``; the family thesis is
    backend variety with identical behavior, and before this contract the
    two backends diverged (igraph silently returned ``[]``, NetworkX leaked
    a raw ``networkx.NetworkXError``). Enforced family-wide by the
    ``test_unknown_start_node_raises_typed_error`` contract test.
    """

    def __init__(self, connector_id: str, start_node: Any) -> None:
        super().__init__(f"{connector_id}: start_node {start_node!r} is not present in the loaded graph.")
        self.connector_id = connector_id
        self.start_node = start_node


class EmbeddedGraphReader(ParamReader):
    """Family base for embedded graph backends.

    Concrete plugins (NetworkxEmbeddedReader, IGraphReader, ...) load a graph
    object from a filesystem path or accept ``locator=None`` for empty graph.
    The backend is in-process, so there is no network surface to configure.

    Per-call inputs (``operation``, ``start_node``) live on
    ``PARAMS_MAPPING`` rather than being read raw from
    ``feature.options.context``. ``operation`` is strict-enum-validated;
    ``start_node`` is free-form (only required when ``operation=neighbors``,
    which the concrete reader enforces at runtime; this is a one-of-N param
    dependency that REQUIRED_PARAMS can't express directly).
    """

    PROPERTY_MAPPING: ClassVar[dict[str, Any]] = compose_property_mapping(
        ParamReader.PROPERTY_MAPPING,
        {
            "graph_file_format": {
                "explanation": "Graph serialisation format the locator points at.",
                "allowed_values": _GRAPH_FILE_FORMATS,
                DefaultOptionKeys.context: True,
                DefaultOptionKeys.strict_validation: True,
                DefaultOptionKeys.default: "gml",
            },
            "read_only": {
                "explanation": "Open the graph in read-only mode (advisory; concrete plugin enforces).",
                DefaultOptionKeys.context: True,
                DefaultOptionKeys.strict_validation: False,
                DefaultOptionKeys.default: True,
            },
            "max_threads": {
                "explanation": "Soft cap on background worker threads; concrete plugin honors if relevant.",
                DefaultOptionKeys.context: True,
                DefaultOptionKeys.strict_validation: False,
                DefaultOptionKeys.default: 1,
            },
        },
        context="EmbeddedGraphReader",
    )

    # Honest surface (option 3, see base.py): advisory backend knobs neither
    # in-process concrete enforces (whole-graph, single-threaded), reserved for a
    # backend that can.
    _WAIVED_UNCONSUMED_KEYS: ClassVar[frozenset[str]] = frozenset({"read_only", "max_threads"})

    PARAMS_MAPPING: ClassVar[dict[str, Any]] = compose_property_mapping(
        {
            "operation": {
                "explanation": "Per-call operation against the embedded graph.",
                "allowed_values": _OPERATIONS,
                DefaultOptionKeys.context: True,
                DefaultOptionKeys.strict_validation: True,
                DefaultOptionKeys.default: "nodes",
            },
            "start_node": {
                "explanation": "Starting node id for `operation=neighbors`; ignored for nodes/edges.",
                DefaultOptionKeys.context: True,
                DefaultOptionKeys.strict_validation: False,
                DefaultOptionKeys.default: None,
            },
        },
        context="EmbeddedGraphReader.PARAMS_MAPPING",
    )

    REQUIRED_PARAMS: ClassVar[tuple[tuple[str, ...], ...]] = (("operation",),)


class EmbeddedGraphFeatureGroup(KgConnectorFeatureGroupBase):
    READER_CLASS = None
