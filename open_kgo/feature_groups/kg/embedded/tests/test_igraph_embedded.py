"""Concrete tests for IGraphEmbeddedReader.

Reuses the committed ``triangle.gml`` fixture (shared with the NetworkX
embedded reader) so both embedded backends are asserted against the same
graph, demonstrating the family base generalises across libraries.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable


from mloda.user import Feature, Options

from open_kgo.feature_groups.kg.embedded.igraph_embedded import IGraphEmbeddedReader
from open_kgo.feature_groups.kg.embedded.tests.kg_embedded_contract import (
    EmbeddedContractTestBase,
)
from open_kgo.feature_groups.kg.tests._helpers import make_valid_credentials


_FIXTURE_GML = Path(__file__).parent / "fixtures" / "triangle.gml"
_FIXTURE_DIRECTED_GML = Path(__file__).parent / "fixtures" / "directed_chain.gml"

# Directed chain alice -> bob -> carol, the GraphML twin of directed_chain.gml.
# igraph surfaces the GraphML node id as the ``id`` vertex attribute, so
# ``_vertex_key`` keys rows on it (matching ``nx.read_graphml``'s node ids).
_GRAPHML_CHAIN = """<?xml version="1.0" encoding="UTF-8"?>
<graphml xmlns="http://graphml.graphdrawing.org/xmlns">
  <graph id="G" edgedefault="directed">
    <node id="alice"/>
    <node id="bob"/>
    <node id="carol"/>
    <edge source="alice" target="bob"/>
    <edge source="bob" target="carol"/>
  </graph>
</graphml>
"""


class TestIGraphEmbeddedReader(EmbeddedContractTestBase):
    @classmethod
    def connector_reader_class(cls) -> type[IGraphEmbeddedReader]:
        return IGraphEmbeddedReader

    @classmethod
    def valid_credentials(cls) -> dict[str, Any]:
        return make_valid_credentials(cls.connector_reader_class(), locator=str(_FIXTURE_GML), result_limit=100)

    @classmethod
    def invalid_credentials(cls) -> dict[str, Any]:
        return {
            "igraph_embedded": {
                "locator": str(_FIXTURE_GML),
                "graph_file_format": "evil_format",
            }
        }

    @classmethod
    def feature_under_test(cls) -> Feature:
        return Feature(
            "igraph_embedded__nodes",
            options=Options(context={"operation": "nodes"}),
        )

    @classmethod
    def expected_row_shape(cls) -> Callable[[Any], bool]:
        return lambda result: isinstance(result, list) and len(result) > 0

    def test_nodes_operation_returns_three_labels(self) -> None:
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        feat = self.feature_under_test()
        rows = run_query("igraph_embedded", self.valid_credentials()["igraph_embedded"], feat)
        assert sorted(r["node"] for r in rows) == ["alice", "bob", "carol"]

    def test_neighbors_operation(self) -> None:
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        feat = Feature(
            "igraph_embedded__neighbors",
            options=Options(context={"operation": "neighbors", "start_node": "alice"}),
        )
        rows = run_query("igraph_embedded", self.valid_credentials()["igraph_embedded"], feat)
        assert sorted(r["node"] for r in rows) == ["bob", "carol"]

    def test_directed_neighbors_are_out_successors_only(self) -> None:
        """On a DIRECTED graph, neighbors(mode="out") yields successors only.

        The undirected ``triangle.gml`` cannot exercise the directed-successor
        path (igraph ignores ``mode`` on undirected graphs). The walk starts at
        ``bob`` (in=``{alice}``, out=``{carol}``) precisely so the fix is
        guarded: out-neighbors are ``["carol"]``, whereas a regression back to
        igraph's default ``mode="all"`` would also include the predecessor
        ``alice``. The result matches the NetworkX sibling's ``DiGraph.neighbors``
        (successors) on the same fixture.
        """
        # Import the sibling module so its FeatureGroup is registered even when
        # this test file runs in isolation (plugin discovery is import-driven).
        import open_kgo.feature_groups.kg.embedded.networkx_embedded  # noqa: F401
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        slot = {"locator": str(_FIXTURE_DIRECTED_GML), "graph_file_format": "gml"}
        feat = Feature(
            "igraph_embedded__dir_neighbors",
            options=Options(context={"operation": "neighbors", "start_node": "bob"}),
        )
        igraph_rows = run_query("igraph_embedded", slot, feat)
        assert sorted(r["node"] for r in igraph_rows) == ["carol"]

        # Parity with the NetworkX sibling's DiGraph.neighbors (successors) on
        # the same directed fixture.
        nx_feat = Feature(
            "networkx_embedded__dir_neighbors",
            options=Options(context={"operation": "neighbors", "start_node": "bob"}),
        )
        nx_rows = run_query("networkx_embedded", slot, nx_feat)
        assert sorted(r["node"] for r in igraph_rows) == sorted(r["node"] for r in nx_rows)

    def test_directed_edges_operation(self) -> None:
        """The ``edges`` operation (dispatched but otherwise unasserted) returns the directed edges."""
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        slot = {"locator": str(_FIXTURE_DIRECTED_GML), "graph_file_format": "gml"}
        feat = Feature("igraph_embedded__edges", options=Options(context={"operation": "edges"}))
        rows = run_query("igraph_embedded", slot, feat)
        assert sorted((r["src"], r["dst"]) for r in rows) == [("alice", "bob"), ("bob", "carol")]

    def test_graphml_format_loads_and_returns_rows(self, tmp_path: Path) -> None:
        """``graph_file_format=graphml`` is advertised in SUPPORTED_VALUES; prove the loader path works.

        Loads a tmp_path-written GraphML twin of ``directed_chain.gml`` and
        asserts both node identities and directed edges, so the advertised
        format is exercised end-to-end rather than only declared.
        """
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        graphml_path = tmp_path / "chain.graphml"
        graphml_path.write_text(_GRAPHML_CHAIN, encoding="utf-8")
        slot = {"locator": str(graphml_path), "graph_file_format": "graphml"}

        nodes_feat = Feature("igraph_embedded__graphml_nodes", options=Options(context={"operation": "nodes"}))
        node_rows = run_query("igraph_embedded", slot, nodes_feat)
        assert sorted(r["node"] for r in node_rows) == ["alice", "bob", "carol"]

        edges_feat = Feature("igraph_embedded__graphml_edges", options=Options(context={"operation": "edges"}))
        edge_rows = run_query("igraph_embedded", slot, edges_feat)
        assert sorted((r["src"], r["dst"]) for r in edge_rows) == [("alice", "bob"), ("bob", "carol")]
