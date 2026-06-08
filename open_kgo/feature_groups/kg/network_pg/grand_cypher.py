"""GrandCypher-backed embedded Cypher reader.

Second concrete in the ``network_pg`` family alongside ``KuzuCypherReader``:
runs openCypher queries against an in-memory NetworkX graph via the pure-Python
``grand-cypher`` library. Kuzu is an embedded C++ engine; GrandCypher is a
Python Cypher interpreter over NetworkX, so the two share the family's
Cypher-shaped contract on different substrates. Like Kuzu, this backend is
single-process and embedded, so ``read_consistency`` / ``transaction_mode``
are no-ops (waived, not narrowed: real network_pg backends will honor them).

The graph is loaded from a GML / GraphML file at ``locator`` (NetworkX relabels
GML nodes to their ``label``, keeping other attributes such as ``name``). The
Cypher text comes from the Feature's options context under ``query_text``.
GrandCypher returns a columnar ``{column: [values...]}`` dict, which we pivot
into the family's row-oriented ``list[dict]`` shape, capped at ``result_limit``.
"""

from __future__ import annotations

from typing import Any, ClassVar, Mapping

import networkx as nx
from grandcypher import GrandCypher

from mloda.core.abstract_plugins.components.feature_set import FeatureSet

from open_kgo.feature_groups.kg.fixtures import _rejected_scheme
from open_kgo.feature_groups.kg.network_pg.base import (
    NetworkPropertyGraphFeatureGroup,
    NetworkPropertyGraphReader,
)


_LOADERS: dict[str, Any] = {
    ".gml": nx.read_gml,
    ".graphml": nx.read_graphml,
}


class GrandCypherReader(NetworkPropertyGraphReader):
    CONNECTOR_ID: ClassVar[str] = "grand_cypher"
    REQUIRED_KEYS: ClassVar[tuple[tuple[str, ...], ...]] = (("locator",),)
    # Waive read_consistency / transaction_mode: GrandCypher runs over an
    # in-memory NetworkX graph (single process, no replicas / transactions), so
    # both are no-ops here. Narrowing would lock the family contract to the
    # embedded backends' single honored value and force future networked
    # concretes (Neo4j, Memgraph) to widen — the same disposition as Kuzu.
    _WAIVED_ENUM_KEYS: ClassVar[frozenset[str]] = frozenset({"read_consistency", "transaction_mode"})

    @classmethod
    def _connect_from_slot(cls, slot: Mapping[str, Any]) -> nx.Graph:
        """Load the NetworkX graph from ``slot['locator']`` (GML / GraphML).

        Format is selected from the file extension. Remote locators are
        rejected for parity with the other file-backed readers (NetworkX's
        loaders only open local paths). A fresh graph is parsed per call,
        matching ``NetworkxEmbeddedReader`` (NetworkX parsing of the small
        fixtures is cheap; no shared cache is introduced for this family).
        """
        locator = slot.get("locator")
        if not locator:
            return nx.DiGraph()
        bad = _rejected_scheme(locator)
        if bad is not None:
            raise ValueError(
                f"{cls.CONNECTOR_ID}: locator scheme {bad!r} is not permitted; "
                f"only local file paths or file:// URLs are allowed."
            )
        from pathlib import Path

        loader = _LOADERS.get(Path(str(locator)).suffix.lower())
        if loader is None:
            raise ValueError(
                f"{cls.CONNECTOR_ID}: unsupported graph file extension for locator {locator!r}; "
                f"expected one of {sorted(_LOADERS)}."
            )
        return loader(str(locator))

    @classmethod
    def load_data(cls, data_access: Any, features: FeatureSet) -> list[dict[str, Any]]:
        ctx = cls._prepare_load(data_access)
        graph = cls._connect_from_slot(ctx.slot)

        query_text = cls.build_query(features)
        # GrandCypher's ``limit`` bounds the number of matches it materialises,
        # so the row cap is pushed into the engine rather than sliced after a
        # full walk (short-circuit per the result_limit contract).
        columns: dict[str, list[Any]] = GrandCypher(graph, limit=ctx.result_limit).run(query_text)

        if not columns:
            return []
        # GrandCypher returns equal-length columns; pivot to row-oriented dicts.
        row_count = min(len(values) for values in columns.values())
        rows = [{column: values[i] for column, values in columns.items()} for i in range(row_count)]
        return rows[: ctx.result_limit]


class GrandCypherFeatureGroup(NetworkPropertyGraphFeatureGroup):
    READER_CLASS: ClassVar[type[GrandCypherReader]] = GrandCypherReader  # type: ignore[assignment]
