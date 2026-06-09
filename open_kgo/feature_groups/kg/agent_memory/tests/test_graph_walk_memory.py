"""Concrete tests for GraphWalkMemoryReader."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest

from mloda.core.abstract_plugins.components.feature_set import FeatureSet
from mloda.provider import HashableDict
from mloda.user import Feature, Options

from open_kgo.feature_groups.kg.agent_memory.graph_walk_memory import GraphWalkMemoryReader
from open_kgo.feature_groups.kg.agent_memory.tests.kg_agent_memory_contract import (
    AgentMemoryContractTestBase,
)
from open_kgo.feature_groups.kg.errors import (
    FixtureLoadError,
    InvalidCredentialShape,
    UnknownMemoryScopeError,
)


_FIXTURE = Path(__file__).parent / "fixtures" / "graph_memories.json"


class TestGraphWalkMemoryReader(AgentMemoryContractTestBase):
    @classmethod
    def connector_reader_class(cls) -> type[GraphWalkMemoryReader]:
        return GraphWalkMemoryReader

    @classmethod
    def valid_credentials(cls) -> dict[str, Any]:
        return {
            "graph_walk_memory": {
                "locator": str(_FIXTURE),
                "memory_scope_user_id": "user_42",
                "retrieval_mode": "graph",
                "pagination_style": "none",
                "result_limit": 100,
                "threshold": 0.0,
                "mmr_lambda": 0.5,
            }
        }

    @classmethod
    def invalid_credentials(cls) -> dict[str, Any]:
        return {
            "graph_walk_memory": {
                "locator": str(_FIXTURE),
                "memory_scope_user_id": "user_42",
                "retrieval_mode": "evil",
            }
        }

    @classmethod
    def feature_under_test(cls) -> Feature:
        return Feature(
            "graph_walk_memory__from_seed",
            options=Options(context={"query_text": "m1"}),
        )

    @classmethod
    def expected_row_shape(cls) -> Callable[[Any], bool]:
        return lambda result: isinstance(result, list) and len(result) >= 1 and "label" in result[0]

    def test_graph_walk_reaches_transitive_memories(self) -> None:
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        feat = self.feature_under_test()
        rows = run_query("graph_walk_memory", self.valid_credentials()["graph_walk_memory"], feat)
        assert {r["id"] for r in rows} == {"m1", "m2", "m3"}

    def test_disconnected_seed_returns_only_itself(self) -> None:
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        feat = Feature("graph_walk_memory__m4", options=Options(context={"query_text": "m4"}))
        rows = run_query("graph_walk_memory", self.valid_credentials()["graph_walk_memory"], feat)
        assert {r["id"] for r in rows} == {"m4"}

    @pytest.mark.parametrize("mode", ["lexical", "vector", "hybrid"])
    def test_unsupported_retrieval_modes_rejected_at_validate_time(self, mode: str) -> None:
        slot = dict(self.valid_credentials()["graph_walk_memory"])
        slot["retrieval_mode"] = mode
        creds = HashableDict({"graph_walk_memory": slot})
        assert GraphWalkMemoryReader.is_valid_credentials(creds) is False
        with pytest.raises(InvalidCredentialShape):
            GraphWalkMemoryReader._validate_shape(slot)

    def test_unknown_user_id_raises_typed_error(self) -> None:
        slot = dict(self.valid_credentials()["graph_walk_memory"])
        slot["memory_scope_user_id"] = "user_does_not_exist"
        creds = HashableDict({"graph_walk_memory": slot})
        with pytest.raises(UnknownMemoryScopeError):
            GraphWalkMemoryReader.connect(creds)

    def test_reconvergent_node_emitted_exactly_once(self) -> None:
        """The diamond node ``m3`` (reachable via m1->m2->m3 AND m1->m3) is emitted once.

        Asserts against the raw ``load_data`` list (not a set) so a regression
        that double-emits on BFS re-convergence is caught — a set-based
        assertion would silently mask it.
        """
        creds = self.valid_credentials()
        fs = FeatureSet()
        fs.add(self.feature_under_test())
        rows = GraphWalkMemoryReader.load_data(creds, fs)
        ids = [r["id"] for r in rows]
        assert ids.count("m3") == 1
        assert len(ids) == len(set(ids))
        assert set(ids) == {"m1", "m2", "m3"}

    def test_cyclic_graph_bfs_terminates_and_dedups(self, tmp_path: Path) -> None:
        """A cycle (m1->m2->m1) does not loop forever; each node is emitted exactly once.

        The ``seen`` set both terminates the BFS and dedups, so a regression that
        re-enqueues an already-visited node would either spin forever or
        double-emit; pinning the exact ``[m1, m2]`` list catches both.
        """
        fixture = tmp_path / "cycle.json"
        fixture.write_text(
            json.dumps(
                {
                    "user_42": {
                        "nodes": [{"id": "m1", "label": "a"}, {"id": "m2", "label": "b"}],
                        "edges": [{"src": "m1", "tgt": "m2"}, {"src": "m2", "tgt": "m1"}],
                    }
                }
            ),
            encoding="utf-8",
        )
        slot = dict(self.valid_credentials()["graph_walk_memory"])
        slot["locator"] = str(fixture)
        fs = FeatureSet()
        fs.add(self.feature_under_test())
        rows = GraphWalkMemoryReader.load_data({"graph_walk_memory": slot}, fs)
        ids = [r["id"] for r in rows]
        assert ids == ["m1", "m2"]
        assert len(ids) == len(set(ids))

    def test_result_limit_caps_bfs_emission(self) -> None:
        """result_limit bounds the BFS: a 3-node reachable set capped at 2 emits exactly the first two ids.

        BFS from ``m1`` visits ``m1`` then its successors in insertion order
        (``m2`` before ``m3``), so the cap pins ``[m1, m2]`` — a regression that
        sliced a fully-expanded set instead of short-circuiting would be caught.
        """
        slot = dict(self.valid_credentials()["graph_walk_memory"])
        slot["result_limit"] = 2
        fs = FeatureSet()
        fs.add(self.feature_under_test())
        rows = GraphWalkMemoryReader.load_data({"graph_walk_memory": slot}, fs)
        assert [r["id"] for r in rows] == ["m1", "m2"]

    def test_malformed_user_entry_missing_edges_raises_typed_error(self, tmp_path: Path) -> None:
        """A user entry missing the required ``edges`` key raises ``FixtureLoadError``.

        Exercises the ``_validate_user_data`` error branch (duplicated locally
        in this concrete) that the linear-fixture tests never reached.
        """
        fixture = tmp_path / "broken.json"
        fixture.write_text(
            json.dumps({"user_42": {"nodes": [{"id": "m1", "label": "x"}]}}),
            encoding="utf-8",
        )
        slot = dict(self.valid_credentials()["graph_walk_memory"])
        slot["locator"] = str(fixture)
        with pytest.raises(FixtureLoadError):
            GraphWalkMemoryReader.connect(HashableDict({"graph_walk_memory": slot}))
