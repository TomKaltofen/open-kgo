"""Concrete tests for GrandCypherReader.

Runs openCypher against an in-memory NetworkX graph loaded from a committed
GML fixture. Exercises the network_pg property layout against a second Cypher
engine; like Kuzu it does NOT exercise read_consistency / transaction_mode
semantics (both no-op on an embedded backend).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest

from mloda.user import Feature, Options

from open_kgo.feature_groups.kg.network_pg.grand_cypher import GrandCypherReader
from open_kgo.feature_groups.kg.network_pg.tests.kg_network_pg_contract import (
    NetworkPropertyGraphContractTestBase,
)


_FIXTURE_GML = Path(__file__).parent / "fixtures" / "org.gml"


class TestGrandCypherReader(NetworkPropertyGraphContractTestBase):
    @classmethod
    def connector_reader_class(cls) -> type[GrandCypherReader]:
        return GrandCypherReader

    @classmethod
    def valid_credentials(cls) -> dict[str, Any]:
        return {
            "grand_cypher": {
                "locator": str(_FIXTURE_GML),
                "dataset": "default",
                "read_consistency": "read",
                "transaction_mode": "auto",
                "result_limit": 100,
            }
        }

    @classmethod
    def invalid_credentials(cls) -> dict[str, Any]:
        # read_consistency is waived (accepted at the family-allowed set) but a
        # value OUTSIDE that set still rejects via the family enum check.
        return {"grand_cypher": {"locator": str(_FIXTURE_GML), "read_consistency": "evil"}}

    @classmethod
    def feature_under_test(cls) -> Feature:
        return Feature(
            "grand_cypher__list_names",
            options=Options(context={"query_text": "MATCH (n) RETURN n.name"}),
        )

    @classmethod
    def expected_row_shape(cls) -> Callable[[Any], bool]:
        return lambda result: isinstance(result, list) and len(result) == 3

    def test_cypher_returns_three_names(self) -> None:
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        feat = self.feature_under_test()
        rows = run_query("grand_cypher", self.valid_credentials()["grand_cypher"], feat)
        names = sorted(r["n.name"] for r in rows)
        assert names == ["Alice", "Bob", "Carol"]

    def test_directed_edge_query(self) -> None:
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        feat = Feature(
            "grand_cypher__manages",
            options=Options(context={"query_text": "MATCH (a)-[]->(b) RETURN a.name, b.name"}),
        )
        rows = run_query("grand_cypher", self.valid_credentials()["grand_cypher"], feat)
        pairs = sorted((r["a.name"], r["b.name"]) for r in rows)
        assert pairs == [("Alice", "Bob"), ("Bob", "Carol")]

    def test_result_limit_truncates_rows(self) -> None:
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        slot = dict(self.valid_credentials()["grand_cypher"])
        slot["result_limit"] = 2
        feat = self.feature_under_test()
        rows = run_query("grand_cypher", slot, feat)
        assert len(rows) == 2

    def test_http_locator_rejected(self) -> None:
        cls = self.connector_reader_class()
        creds = {cls.CONNECTOR_ID: {"locator": "http://example.com/evil.gml"}}
        with pytest.raises(ValueError, match="scheme"):
            cls.connect(creds)
