"""Concrete tests for IGraphEmbeddedReader.

Reuses the committed ``triangle.gml`` fixture (shared with the NetworkX
embedded reader) so both embedded backends are asserted against the same
graph, demonstrating the family base generalises across libraries.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest

from mloda.user import Feature, Options

from open_kgo.feature_groups.kg.embedded.igraph_embedded import IGraphEmbeddedReader
from open_kgo.feature_groups.kg.embedded.tests.kg_embedded_contract import (
    EmbeddedContractTestBase,
)


_FIXTURE_GML = Path(__file__).parent / "fixtures" / "triangle.gml"
_FIXTURE_DIRECTED_GML = Path(__file__).parent / "fixtures" / "directed_chain.gml"


class TestIGraphEmbeddedReader(EmbeddedContractTestBase):
    @classmethod
    def connector_reader_class(cls) -> type[IGraphEmbeddedReader]:
        return IGraphEmbeddedReader

    @classmethod
    def valid_credentials(cls) -> dict[str, Any]:
        return {
            "igraph_embedded": {
                "locator": str(_FIXTURE_GML),
                "graph_file_format": "gml",
                "read_only": True,
                "max_threads": 1,
                "result_limit": 100,
            }
        }

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

    def test_http_locator_rejected(self) -> None:
        """Remote schemes must be refused, like the other file-backed readers."""
        cls = self.connector_reader_class()
        creds = {cls.CONNECTOR_ID: {"locator": "http://example.com/evil.gml"}}
        with pytest.raises(ValueError, match="scheme"):
            cls.connect(creds)

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
