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
