"""python-igraph-backed embedded graph reader.

Second concrete in the ``embedded`` family alongside ``NetworkxEmbeddedReader``:
loads a graph from a fixture file (.gml / .graphml / .edgelist) at ``locator``
via python-igraph and runs the same family operations (``nodes`` / ``edges`` /
``neighbors``). Demonstrates that the embedded family base generalises across a
second in-memory graph library; no new family surface is unlocked (igraph,
like NetworkX, is an embedded in-process backend), so this is backend variety,
not a new contract branch.

The vertex identity exposed in rows is the first present of ``name`` / ``label``
/ ``id``, falling back to the integer vertex index. The committed GML fixtures
carry a ``label`` per node, so rows key on the label (e.g. ``"alice"``), which
mirrors what ``nx.read_gml`` produces (it relabels nodes to their ``label``).
"""

from __future__ import annotations

from itertools import islice
from typing import Any, ClassVar, Mapping

import igraph

from mloda.core.abstract_plugins.components.feature_set import FeatureSet

from open_kgo.feature_groups.kg.embedded.base import (
    EmbeddedGraphFeatureGroup,
    EmbeddedGraphReader,
)
from open_kgo.feature_groups.kg.fixtures import _rejected_scheme


_LOADERS: dict[str, Any] = {
    "gml": igraph.Graph.Read_GML,
    "graphml": igraph.Graph.Read_GraphML,
    "edgelist": igraph.Graph.Read_Edgelist,
}


def _vertex_key(vertex: igraph.Vertex) -> Any:
    """Return a stable identifier for ``vertex``: first present of name/label/id, else index.

    igraph vertices are integer-indexed; GML/GraphML readers surface the
    source identifiers as the ``name`` / ``label`` / ``id`` attributes. The
    NetworkX reader keys rows on the node id (its GML loader relabels nodes to
    their ``label``), so preferring ``name`` then ``label`` keeps the two
    embedded backends' row shapes aligned on the same committed fixtures. The
    integer-index fallback covers plain edge lists, whose vertices carry no
    attributes.
    """
    attrs = vertex.attributes()
    for attr in ("name", "label", "id"):
        value = attrs.get(attr)
        if value is not None:
            return value
    return vertex.index


class IGraphEmbeddedReader(EmbeddedGraphReader):
    CONNECTOR_ID: ClassVar[str] = "igraph_embedded"
    # Strict-enum dispositions mirror NetworkxEmbeddedReader: every
    # family-advertised graph_file_format is wired into ``_LOADERS`` and every
    # operation is dispatched in ``load_data``. Mirroring the full family set
    # (rather than leaving it implicit) makes a future family-level addition
    # surface here as a contract failure instead of a silent drop.
    SUPPORTED_VALUES: ClassVar[Mapping[str, frozenset[Any]]] = {
        "graph_file_format": frozenset({"gml", "graphml", "edgelist"}),
        "operation": frozenset({"nodes", "edges", "neighbors"}),
    }

    @classmethod
    def _connect_from_slot(cls, slot: Mapping[str, Any]) -> igraph.Graph:
        locator = slot.get("locator")
        if not locator:
            return igraph.Graph()
        # Reject remote locators for parity with the other file-backed readers;
        # igraph's loaders only open local paths, so this keeps the file-only
        # contract uniform across families.
        bad = _rejected_scheme(locator)
        if bad is not None:
            raise ValueError(
                f"{cls.CONNECTOR_ID}: locator scheme {bad!r} is not permitted; "
                f"only local file paths or file:// URLs are allowed."
            )
        fmt = slot.get("graph_file_format", "gml")
        loader = _LOADERS.get(fmt)
        if loader is None:
            raise ValueError(f"{cls.CONNECTOR_ID}: unsupported graph_file_format={fmt!r}")
        return loader(str(locator))

    @classmethod
    def load_data(cls, data_access: Any, features: FeatureSet) -> list[dict[str, Any]]:
        ctx = cls._prepare_load(data_access)
        graph = cls._connect_from_slot(ctx.slot)

        params = cls.build_params(features, ctx.slot)
        op = params["operation"]

        if op == "nodes":
            return [{"node": _vertex_key(v)} for v in islice(graph.vs, ctx.result_limit)]
        if op == "edges":
            return [
                {"src": _vertex_key(graph.vs[e.source]), "dst": _vertex_key(graph.vs[e.target])}
                for e in islice(graph.es, ctx.result_limit)
            ]
        if op == "neighbors":
            start = params.get("start_node")
            if start is None:
                raise ValueError(f"{cls.CONNECTOR_ID}: operation=neighbors requires 'start_node'.")
            start_indices = [v.index for v in graph.vs if _vertex_key(v) == start]
            if not start_indices:
                return []
            neighbors = islice(graph.neighbors(start_indices[0]), ctx.result_limit)
            return [{"node": _vertex_key(graph.vs[n])} for n in neighbors]
        raise ValueError(f"{cls.CONNECTOR_ID}: unsupported operation={op!r}")


class IGraphEmbeddedFeatureGroup(EmbeddedGraphFeatureGroup):
    READER_CLASS: ClassVar[type[IGraphEmbeddedReader]] = IGraphEmbeddedReader  # type: ignore[assignment]
