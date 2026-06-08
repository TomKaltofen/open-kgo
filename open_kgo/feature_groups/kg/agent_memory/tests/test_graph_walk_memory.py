"""Concrete tests for GraphWalkMemoryReader."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest

from mloda.provider import HashableDict
from mloda.user import Feature, Options

from open_kgo.feature_groups.kg.agent_memory.graph_walk_memory import GraphWalkMemoryReader
from open_kgo.feature_groups.kg.agent_memory.tests.kg_agent_memory_contract import (
    AgentMemoryContractTestBase,
)
from open_kgo.feature_groups.kg.errors import InvalidCredentialShape, UnknownMemoryScopeError


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
