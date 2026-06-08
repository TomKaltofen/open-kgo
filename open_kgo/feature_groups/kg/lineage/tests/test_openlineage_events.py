"""Concrete tests for OpenLineageReader."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from mloda.user import Feature, Options

from open_kgo.feature_groups.kg.lineage.openlineage_events import OpenLineageReader
from open_kgo.feature_groups.kg.lineage.tests.kg_lineage_contract import (
    LineageContractTestBase,
)


_FIXTURE = Path(__file__).parent / "fixtures" / "openlineage_events.json"


class TestOpenLineageReader(LineageContractTestBase):
    @classmethod
    def connector_reader_class(cls) -> type[OpenLineageReader]:
        return OpenLineageReader

    @classmethod
    def valid_credentials(cls) -> dict[str, Any]:
        return {
            "openlineage_events": {
                "locator": str(_FIXTURE),
                "result_limit": 100,
            }
        }

    @classmethod
    def invalid_credentials(cls) -> dict[str, Any]:
        # Bad ``lineage_direction`` value triggers the SUPPORTED_VALUES narrowing.
        return {"openlineage_events": {"locator": str(_FIXTURE), "lineage_direction": "SIDEWAYS"}}

    @classmethod
    def feature_under_test(cls) -> Feature:
        return Feature(
            "openlineage_events__upstream",
            options=Options(
                context={
                    "asset_urn": "fct_orders",
                    "lineage_direction": "UPSTREAM",
                    "upstream_depth": 2,
                    "downstream_depth": 0,
                }
            ),
        )

    @classmethod
    def expected_row_shape(cls) -> Callable[[Any], bool]:
        return lambda result: isinstance(result, list) and len(result) >= 1 and "name" in result[0]

    def test_upstream_walk_two_hops(self) -> None:
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        feat = self.feature_under_test()
        rows = run_query("openlineage_events", self.valid_credentials()["openlineage_events"], feat)
        names = {r["name"] for r in rows}
        assert names == {"fct_orders", "stg_orders", "raw.orders"}

    def test_downstream_walk(self) -> None:
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        feat = Feature(
            "openlineage_events__downstream",
            options=Options(
                context={
                    "asset_urn": "fct_orders",
                    "lineage_direction": "DOWNSTREAM",
                    "upstream_depth": 0,
                    "downstream_depth": 1,
                }
            ),
        )
        rows = run_query("openlineage_events", self.valid_credentials()["openlineage_events"], feat)
        names = {r["name"] for r in rows}
        assert names == {"fct_orders", "report_daily"}
