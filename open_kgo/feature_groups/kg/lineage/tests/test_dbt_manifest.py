"""Concrete tests for DbtManifestReader."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from mloda.user import Feature, Options

from open_kgo.feature_groups.kg.lineage.dbt_manifest import DbtManifestReader
from open_kgo.feature_groups.kg.lineage.tests.kg_lineage_contract import (
    LineageContractTestBase,
)
from open_kgo.feature_groups.kg.tests._helpers import make_valid_credentials


_FIXTURE = Path(__file__).parent / "fixtures" / "manifest.json"


class TestDbtManifestReader(LineageContractTestBase):
    @classmethod
    def connector_reader_class(cls) -> type[DbtManifestReader]:
        return DbtManifestReader

    @classmethod
    def valid_credentials(cls) -> dict[str, Any]:
        return make_valid_credentials(cls.connector_reader_class(), locator=str(_FIXTURE), result_limit=100)

    @classmethod
    def invalid_credentials(cls) -> dict[str, Any]:
        # ``lineage_direction`` is a PARAMS key, so in the credential slot it is
        # rejected by the closed-world unknown-credential-key check. (The
        # strict-enum narrowing for it is exercised per-call by the inherited
        # ``test_strict_validation_params_enums_rejected_per_key``.) The earlier
        # ``auth_method="evil"`` seed went away with the universal auth surface.
        return {"dbt_manifest": {"locator": str(_FIXTURE), "lineage_direction": "SIDEWAYS"}}

    @classmethod
    def feature_under_test(cls) -> Feature:
        return Feature(
            "dbt_manifest__upstream",
            options=Options(
                context={
                    "asset_urn": "model.shop.fct_orders",
                    "lineage_direction": "UPSTREAM",
                    "upstream_depth": 2,
                    "downstream_depth": 0,
                }
            ),
        )

    @classmethod
    def expected_row_shape(cls) -> Callable[[Any], bool]:
        return lambda result: isinstance(result, list) and len(result) >= 1 and "urn" in result[0]

    def test_upstream_walk_two_hops(self) -> None:
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        feat = self.feature_under_test()
        rows = run_query("dbt_manifest", self.valid_credentials()["dbt_manifest"], feat)
        urns = [r["urn"] for r in rows]
        assert "model.shop.fct_orders" in urns
        assert "model.shop.stg_orders" in urns
        assert "source.shop.raw.orders" in urns

    def test_both_direction_emits_cycle_node_once(self, tmp_path: Path) -> None:
        """A node both upstream AND downstream of the start (cycle) appears once under BOTH.

        ``parent_map`` / ``child_map`` form the cycle A <-> B, so from ``A``
        the node ``B`` is reachable in both directions. The two directional
        walks share one EMITTED set; a regression to per-walk emission dedup
        would emit ``B`` twice and double-bill result_limit.
        """
        import json

        from open_kgo.feature_groups.kg.tests._helpers import run_query

        manifest = {
            "nodes": {
                "model.shop.a": {"name": "a"},
                "model.shop.b": {"name": "b"},
            },
            "parent_map": {"model.shop.a": ["model.shop.b"], "model.shop.b": ["model.shop.a"]},
            "child_map": {"model.shop.a": ["model.shop.b"], "model.shop.b": ["model.shop.a"]},
        }
        fixture = tmp_path / "manifest.json"
        fixture.write_text(json.dumps(manifest), encoding="utf-8")
        feat = Feature(
            "dbt_manifest__cycle_both",
            options=Options(
                context={
                    "asset_urn": "model.shop.a",
                    "lineage_direction": "BOTH",
                    "upstream_depth": 1,
                    "downstream_depth": 1,
                }
            ),
        )
        rows = run_query("dbt_manifest", {"locator": str(fixture)}, feat)
        urns = [r["urn"] for r in rows]
        assert sorted(urns) == ["model.shop.a", "model.shop.b"], f"expected each node once, got {urns}"

    def test_both_direction_expands_overlap_node_reached_by_first_walk(self, tmp_path: Path) -> None:
        """A node beyond an overlap node is still reached by the second walk under BOTH.

        Topology: ``parent_map`` A -> [B] (B is upstream of A); ``child_map``
        A -> [C], C -> [B], B -> [D] (downstream chain A, C, B, D). The
        upstream walk emits B first; the downstream walk reaches B again via
        C and must still EXPAND it (without re-emitting it) so D is returned.
        A regression to one seen set shared for traversal would stop the
        downstream walk at B and silently drop D.
        """
        import json

        from open_kgo.feature_groups.kg.tests._helpers import run_query

        manifest = {
            "nodes": {
                "model.shop.a": {"name": "a"},
                "model.shop.b": {"name": "b"},
                "model.shop.c": {"name": "c"},
                "model.shop.d": {"name": "d"},
            },
            "parent_map": {"model.shop.a": ["model.shop.b"]},
            "child_map": {
                "model.shop.a": ["model.shop.c"],
                "model.shop.c": ["model.shop.b"],
                "model.shop.b": ["model.shop.d"],
            },
        }
        fixture = tmp_path / "manifest.json"
        fixture.write_text(json.dumps(manifest), encoding="utf-8")
        feat = Feature(
            "dbt_manifest__overlap_both",
            options=Options(
                context={
                    "asset_urn": "model.shop.a",
                    "lineage_direction": "BOTH",
                    "upstream_depth": 1,
                    "downstream_depth": 3,
                }
            ),
        )
        rows = run_query("dbt_manifest", {"locator": str(fixture)}, feat)
        urns = [r["urn"] for r in rows]
        assert sorted(urns) == [
            "model.shop.a",
            "model.shop.b",
            "model.shop.c",
            "model.shop.d",
        ], f"expected every node exactly once (D beyond the overlap node B), got {urns}"
