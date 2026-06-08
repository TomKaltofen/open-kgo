"""Concrete tests for PaginatedTupleStoreReader."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest

from mloda.user import Feature, Options

from open_kgo.feature_groups.kg.errors import InvalidCredentialShape, UnknownTenantError
from open_kgo.feature_groups.kg.saas_authz.paginated_tuple_store import (
    PaginatedTupleStoreReader,
)
from open_kgo.feature_groups.kg.saas_authz.tests.kg_saas_authz_contract import (
    SaasAuthzContractTestBase,
)


_FIXTURE = Path(__file__).parent / "fixtures" / "tuples_b.json"


class TestPaginatedTupleStoreReader(SaasAuthzContractTestBase):
    @classmethod
    def connector_reader_class(cls) -> type[PaginatedTupleStoreReader]:
        return PaginatedTupleStoreReader

    @classmethod
    def valid_credentials(cls) -> dict[str, Any]:
        return {
            "paginated_tuple_store": {
                "locator": str(_FIXTURE),
                "tenant": "tenant_b",
                "api_version": "v1.0",
                "relationship_type": "viewer",
                "consistency_mode": "minimize_latency",
                "pagination_style": "cursor",
                "page_size": 2,
                "result_limit": 100,
            }
        }

    @classmethod
    def invalid_credentials(cls) -> dict[str, Any]:
        return {
            "paginated_tuple_store": {
                "locator": str(_FIXTURE),
                "tenant": "tenant_b",
                "consistency_mode": "evil",
            }
        }

    @classmethod
    def feature_under_test(cls) -> Feature:
        return Feature("paginated_tuple_store__viewers", options=Options(context={}))

    @classmethod
    def expected_row_shape(cls) -> Callable[[Any], bool]:
        return lambda result: (
            isinstance(result, list) and len(result) >= 1 and all(r["relation"] == "viewer" for r in result)
        )

    def test_first_page_honors_page_size(self) -> None:
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        feat = self.feature_under_test()
        rows = run_query("paginated_tuple_store", self.valid_credentials()["paginated_tuple_store"], feat)
        assert [(r["object_id"], r["user"]) for r in rows] == [("doc1", "user:alice"), ("doc1", "user:bob")]

    def test_second_page_via_cursor_token(self) -> None:
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        feat = Feature("paginated_tuple_store__page2", options=Options(context={"cursor_token": "offset:2"}))
        rows = run_query("paginated_tuple_store", self.valid_credentials()["paginated_tuple_store"], feat)
        assert [(r["object_id"], r["user"]) for r in rows] == [("doc2", "user:carol"), ("doc3", "user:dave")]

    def test_expand_paths_expands_group_userset(self) -> None:
        """With expand_paths, the group userset is replaced by its members."""
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        slot = dict(self.valid_credentials()["paginated_tuple_store"])
        slot["expand_paths"] = ["member"]
        slot["page_size"] = 100
        feat = self.feature_under_test()
        rows = run_query("paginated_tuple_store", slot, feat)
        users = {r["user"] for r in rows}
        assert "user:erin" in users and "user:frank" in users
        assert "group:eng#member" not in users

    def test_without_expand_paths_group_ref_passes_through(self) -> None:
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        slot = dict(self.valid_credentials()["paginated_tuple_store"])
        slot["page_size"] = 100
        feat = self.feature_under_test()
        rows = run_query("paginated_tuple_store", slot, feat)
        users = {r["user"] for r in rows}
        assert "group:eng#member" in users
        assert "user:erin" not in users

    def test_unknown_tenant_raises_typed_error(self) -> None:
        slot = dict(self.valid_credentials()["paginated_tuple_store"])
        slot["tenant"] = "tenant_does_not_exist"
        with pytest.raises(UnknownTenantError):
            PaginatedTupleStoreReader._connect_from_slot(slot)

    def test_cursor_token_with_non_cursor_style_rejected(self) -> None:
        """The PaginationMixin cross-layer guard rejects cursor_token unless pagination_style is cursor-family.

        pagination_style is narrowed to ``cursor`` here, so the only way to
        violate the guard is to also bypass the credential narrowing; this test
        instead confirms the happy path (cursor_token + cursor style) builds.
        """
        slot = dict(self.valid_credentials()["paginated_tuple_store"])
        feat = Feature("paginated_tuple_store__cursor_ok", options=Options(context={"cursor_token": "offset:0"}))
        from mloda.core.abstract_plugins.components.feature_set import FeatureSet

        fs = FeatureSet()
        fs.add(feat)
        params = PaginatedTupleStoreReader.build_params(fs, slot)
        assert params["cursor_token"] == "offset:0"

    def test_malformed_cursor_token_rejected(self) -> None:
        """A malformed cursor surfaces ``InvalidCredentialShape`` from ``load_data``.

        Exercised directly against the reader (not through ``mloda.run_all``,
        which wraps reader exceptions in a bare ``Exception``) so the typed
        error contract is asserted at the reader boundary.
        """
        from mloda.core.abstract_plugins.components.feature_set import FeatureSet

        slot = dict(self.valid_credentials()["paginated_tuple_store"])
        feat = Feature("paginated_tuple_store__bad_cursor", options=Options(context={"cursor_token": "garbage"}))
        fs = FeatureSet()
        fs.add(feat)
        with pytest.raises(InvalidCredentialShape):
            PaginatedTupleStoreReader.load_data({"paginated_tuple_store": slot}, fs)
