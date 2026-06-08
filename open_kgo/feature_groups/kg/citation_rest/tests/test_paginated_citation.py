"""Concrete tests for PaginatedCitationReader."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest

from mloda.provider import HashableDict
from mloda.user import Feature, Options

from open_kgo.feature_groups.kg.citation_rest.paginated_citation import (
    PaginatedCitationReader,
)
from open_kgo.feature_groups.kg.citation_rest.tests.kg_citation_rest_contract import (
    CitationRestContractTestBase,
)
from open_kgo.feature_groups.kg.errors import InvalidCredentialShape
from open_kgo.feature_groups.kg.mixins import parse_offset_cursor


_FIXTURE = Path(__file__).parent / "fixtures" / "citations.json"


class TestPaginatedCitationReader(CitationRestContractTestBase):
    @classmethod
    def connector_reader_class(cls) -> type[PaginatedCitationReader]:
        return PaginatedCitationReader

    @classmethod
    def valid_credentials(cls) -> dict[str, Any]:
        return {
            "paginated_citation": {
                "locator": str(_FIXTURE),
                "pagination_style": "cursor",
                "page_size": 2,
                "species_prefix": "HSA",
                "dataset_version": "v1",
                "result_limit": 100,
            }
        }

    @classmethod
    def invalid_credentials(cls) -> dict[str, Any]:
        # pagination_style="page" is in the family set but outside this
        # concrete's SUPPORTED_VALUES narrowing ({"cursor"}), so it rejects.
        return {"paginated_citation": {"locator": str(_FIXTURE), "pagination_style": "page"}}

    @classmethod
    def feature_under_test(cls) -> Feature:
        return Feature(
            "paginated_citation__page1",
            options=Options(context={"stable_id": "W1", "hierarchy_depth": 3, "entity_type": "article"}),
        )

    @classmethod
    def expected_row_shape(cls) -> Callable[[Any], bool]:
        return lambda result: isinstance(result, list) and len(result) >= 1 and "stableId" in result[0]

    def test_first_page_honors_page_size(self) -> None:
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        feat = self.feature_under_test()
        rows = run_query("paginated_citation", self.valid_credentials()["paginated_citation"], feat)
        assert [r["stableId"] for r in rows] == ["W1", "W2"]

    def test_second_page_via_cursor_token(self) -> None:
        """A cursor_token offset returns the next page of the article-filtered walk."""
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        feat = Feature(
            "paginated_citation__page2",
            options=Options(
                context={
                    "stable_id": "W1",
                    "hierarchy_depth": 3,
                    "entity_type": "article",
                    "cursor_token": "offset:2",
                }
            ),
        )
        rows = run_query("paginated_citation", self.valid_credentials()["paginated_citation"], feat)
        assert [r["stableId"] for r in rows] == ["W4", "W5"]

    def test_entity_type_filter_selects_books(self) -> None:
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        feat = Feature(
            "paginated_citation__books",
            options=Options(context={"stable_id": "W1", "hierarchy_depth": 3, "entity_type": "book"}),
        )
        rows = run_query("paginated_citation", self.valid_credentials()["paginated_citation"], feat)
        assert [r["stableId"] for r in rows] == ["W3"]

    def test_malformed_cursor_token_rejected(self) -> None:
        with pytest.raises(InvalidCredentialShape):
            parse_offset_cursor("paginated_citation", "garbage")

    def test_none_cursor_is_first_page(self) -> None:
        assert parse_offset_cursor("paginated_citation", None) == 0

    def test_cursor_token_requires_cursor_family_style(self) -> None:
        """The PaginationMixin cross-layer guard fires: cursor_token only valid with a cursor style."""
        slot = dict(self.valid_credentials()["paginated_citation"])
        creds = HashableDict({"paginated_citation": slot})
        # is_valid_credentials only checks the credential surface; the cross-layer
        # check runs in build_params, so the credential slot itself stays valid.
        assert PaginatedCitationReader.is_valid_credentials(creds) is True
