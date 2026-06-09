"""Concrete tests for PaginatedCitationReader."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest

from mloda.core.abstract_plugins.components.feature_set import FeatureSet
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

    def test_short_final_page_returns_tail(self) -> None:
        """A cursor offset landing one short of the end returns just the tail id.

        The article-filtered, sorted walk is ``[W1, W2, W4, W5]``; ``offset:3``
        with ``page_size=2`` slices ``[3:5]`` -> the single remaining id ``W5``.
        """
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        feat = Feature(
            "paginated_citation__tail",
            options=Options(
                context={
                    "stable_id": "W1",
                    "hierarchy_depth": 3,
                    "entity_type": "article",
                    "cursor_token": "offset:3",
                }
            ),
        )
        rows = run_query("paginated_citation", self.valid_credentials()["paginated_citation"], feat)
        assert [r["stableId"] for r in rows] == ["W5"]

    @pytest.mark.parametrize("bad", [0, -1, "abc", True, False])
    def test_invalid_page_size_rejected(self, bad: object) -> None:
        """A non-positive-int / non-numeric / bool page_size raises InvalidCredentialShape at load time."""
        slot = dict(self.valid_credentials()["paginated_citation"])
        slot["page_size"] = bad
        fs = FeatureSet()
        fs.add(self.feature_under_test())
        with pytest.raises(InvalidCredentialShape):
            PaginatedCitationReader.load_data({"paginated_citation": slot}, fs)

    @pytest.mark.parametrize("bad", ["garbage", True, "offset:-1"])
    def test_malformed_cursor_token_rejected(self, bad: object) -> None:
        """A non-``offset:<N>`` / bool / negative-offset cursor raises InvalidCredentialShape."""
        with pytest.raises(InvalidCredentialShape):
            parse_offset_cursor("paginated_citation", bad)

    def test_none_cursor_is_first_page(self) -> None:
        assert parse_offset_cursor("paginated_citation", None) == 0

    def test_cursor_token_requires_cursor_family_style(self) -> None:
        """The PaginationMixin cross-layer guard fires through ``build_params``.

        Exercises the real rejection path, not just ``is_valid_credentials``
        (which never runs ``_validate_cross_layer``). The reader narrows
        ``pagination_style`` to ``{"cursor"}``, so a non-cursor value can't be
        placed in the slot; instead the slot OMITS ``pagination_style`` (the
        cross-layer hook defaults it to ``"none"``) while the feature carries a
        ``cursor_token``, which is the misconfiguration the guard rejects.
        """
        fs = FeatureSet()
        fs.add(
            Feature(
                "paginated_citation__cursor",
                options=Options(context={"stable_id": "W1", "cursor_token": "offset:2"}),
            )
        )
        creds = {"locator": str(_FIXTURE)}
        with pytest.raises(InvalidCredentialShape, match="cursor-family"):
            PaginatedCitationReader.build_params(fs, creds)

    def test_result_limit_caps_below_page_size(self) -> None:
        """result_limit smaller than page_size truncates the page to result_limit rows."""
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        slot = dict(self.valid_credentials()["paginated_citation"])
        slot["page_size"] = 2
        slot["result_limit"] = 1
        feat = self.feature_under_test()
        rows = run_query("paginated_citation", slot, feat)
        assert [r["stableId"] for r in rows] == ["W1"]

    def test_overflow_cursor_offset_yields_empty_page(self) -> None:
        """A cursor offset past the end of the collected walk returns an empty page."""
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        feat = Feature(
            "paginated_citation__overflow",
            options=Options(
                context={
                    "stable_id": "W1",
                    "hierarchy_depth": 3,
                    "entity_type": "article",
                    "cursor_token": "offset:99",
                }
            ),
        )
        rows = run_query("paginated_citation", self.valid_credentials()["paginated_citation"], feat)
        assert rows == []
