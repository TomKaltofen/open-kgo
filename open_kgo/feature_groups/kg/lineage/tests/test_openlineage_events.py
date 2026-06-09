"""Concrete tests for OpenLineageReader."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from mloda.user import Feature, Options

from open_kgo.feature_groups.kg.lineage.openlineage_events import (
    OpenLineageReader,
    _build_dataset_graph,
)
from open_kgo.feature_groups.kg.lineage.tests.kg_lineage_contract import (
    LineageContractTestBase,
)
from open_kgo.feature_groups.kg.tests._helpers import run_query


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
        # ``lineage_direction`` is a PARAMS key, so in the credential slot it is
        # rejected by the closed-world unknown-credential-key check. (The
        # strict-enum narrowing for it is exercised per-call by the inherited
        # ``test_strict_validation_params_enums_rejected_per_key``.)
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

    def test_result_limit_bounds_both_direction_walk(self) -> None:
        """``result_limit`` caps the BOTH walk, bounding cost rather than slicing at the end.

        From ``fct_orders`` the BOTH-direction reachable set is four datasets
        (fct_orders, stg_orders, raw.orders, report_daily); ``result_limit=2``
        must emit exactly two rows, so a regression where ``_walk`` overshoots
        the remaining budget (or load_data fails to short-circuit) is caught for
        this concrete, not only ``DbtManifestReader``.
        """
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        slot = dict(self.valid_credentials()["openlineage_events"])
        slot["result_limit"] = 2
        feat = Feature(
            "openlineage_events__both_capped",
            options=Options(
                context={
                    "asset_urn": "fct_orders",
                    "lineage_direction": "BOTH",
                    "upstream_depth": 2,
                    "downstream_depth": 1,
                }
            ),
        )
        rows = run_query("openlineage_events", slot, feat)
        assert len(rows) == 2
        assert {r["name"] for r in rows} == {"fct_orders", "stg_orders"}

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


# --- Graph-construction unit tests (the merge/dedup behaviour that
# distinguishes this plugin from DbtManifestReader, plus the defensive
# malformed-event skip). ``_build_dataset_graph`` returns
# ``(upstream_map, downstream_map, namespace_index)``.


def test_build_graph_dedupes_duplicate_edge_across_events() -> None:
    """The same input->output edge emitted by two events is counted once.

    ``upstream``/``downstream`` are ``set``s, so a duplicate edge dedupes
    naturally; this pins that no-double-count behaviour as load-bearing.
    """
    events = [
        {"inputs": [{"name": "a", "namespace": "ns"}], "outputs": [{"name": "b", "namespace": "ns"}]},
        {"inputs": [{"name": "a", "namespace": "ns"}], "outputs": [{"name": "b", "namespace": "ns"}]},
    ]
    upstream, downstream, _ = _build_dataset_graph(events)
    assert upstream == {"b": {"a"}}
    assert downstream == {"a": {"b"}}


def test_build_graph_merges_start_no_outputs_with_complete_pair() -> None:
    """A START event with no outputs + a COMPLETE event merge into a single edge.

    eventType is ignored by design (documented): the START contributes only
    its (empty) outputs, so the merged dataset graph carries exactly the one
    edge the COMPLETE event produced.
    """
    events = [
        {"eventType": "START", "inputs": [{"name": "x", "namespace": "ns"}], "outputs": []},
        {
            "eventType": "COMPLETE",
            "inputs": [{"name": "x", "namespace": "ns"}],
            "outputs": [{"name": "y", "namespace": "ns"}],
        },
    ]
    upstream, downstream, namespaces = _build_dataset_graph(events)
    assert upstream == {"y": {"x"}}
    assert downstream == {"x": {"y"}}
    assert set(namespaces) == {"x", "y"}


def test_build_graph_emits_cartesian_edges_for_multi_input_multi_output() -> None:
    """An event with N inputs and M outputs yields the full N*M edge set."""
    events = [
        {
            "inputs": [{"name": "a", "namespace": "ns"}, {"name": "b", "namespace": "ns"}],
            "outputs": [{"name": "c", "namespace": "ns"}, {"name": "d", "namespace": "ns"}],
        }
    ]
    upstream, downstream, _ = _build_dataset_graph(events)
    assert upstream == {"c": {"a", "b"}, "d": {"a", "b"}}
    assert downstream == {"a": {"c", "d"}, "b": {"c", "d"}}


def test_build_graph_skips_event_with_null_inputs() -> None:
    """A present-but-null ``inputs`` is coerced to ``[]``, not iterated as ``None``.

    Regression guard: ``event.get("inputs", [])`` only defaults on an absent
    key, so ``"inputs": null`` previously raised ``TypeError`` and aborted the
    whole build. The bad event is now skipped defensively and the valid edge
    survives.
    """
    events = [
        {"inputs": None, "outputs": [{"name": "junk", "namespace": "ns"}]},
        {"inputs": [{"name": "a", "namespace": "ns"}], "outputs": [{"name": "b", "namespace": "ns"}]},
    ]
    upstream, downstream, _ = _build_dataset_graph(events)
    assert upstream == {"b": {"a"}}
    assert downstream == {"a": {"b"}}


def test_load_data_completes_with_malformed_null_inputs_event(tmp_path: Path) -> None:
    """End-to-end: a ``"inputs": null`` event does not abort ``load_data``.

    The valid downstream edge ``a -> b`` is still walked and returned.
    """
    fixture = tmp_path / "events.json"
    fixture.write_text(
        json.dumps(
            {
                "events": [
                    {"inputs": None, "outputs": [{"name": "junk", "namespace": "ns"}]},
                    {
                        "inputs": [{"name": "a", "namespace": "ns"}],
                        "outputs": [{"name": "b", "namespace": "ns"}],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    feat = Feature(
        "openlineage_events__downstream",
        options=Options(
            context={
                "asset_urn": "a",
                "lineage_direction": "DOWNSTREAM",
                "upstream_depth": 0,
                "downstream_depth": 1,
            }
        ),
    )
    rows = run_query("openlineage_events", {"locator": str(fixture)}, feat)
    names = {r["name"] for r in rows}
    assert names == {"a", "b"}
