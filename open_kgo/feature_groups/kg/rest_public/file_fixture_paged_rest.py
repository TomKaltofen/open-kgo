"""File-fixture REST connector using page-number pagination.

Second concrete in the ``rest_public`` family alongside ``FileFixtureRestReader``
(which uses opaque-cursor pagination). This reader exercises the family's
*counter* pagination branch: ``pagination_style=page`` plus ``page_size`` — the
two surfaces the cursor concrete narrows away (it pins ``pagination_style`` to
``cursor`` and drops ``page_size``). It therefore proves the PaginationMixin's
page/page_size contract is real, modelling page-number APIs such as GBIF or the
GitHub REST API rather than OpenAlex cursors.

The ``locator`` points to a directory of ``page_<N>.json`` files, each shaped
like ``{"results": [...rows...]}``. The reader walks pages in numeric order and
stops at the first page returning fewer than ``page_size`` rows (the standard
page-number end-of-collection signal), or when ``result_limit`` is reached.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, ClassVar, Mapping

from mloda.core.abstract_plugins.components.feature_set import FeatureSet

from open_kgo.feature_groups.kg.fixtures import copy_cached_row, load_json_fixture
from open_kgo.feature_groups.kg.rest_public.base import (
    RestPublicFeatureGroup,
    RestPublicReader,
)


def _page_index(page_file: Path) -> int:
    """Return the integer ``<N>`` from a ``page_<N>.json`` filename for numeric sort."""
    match = re.search(r"\d+", page_file.stem)
    return int(match.group()) if match else 0


class FileFixturePagedRestReader(RestPublicReader):
    CONNECTOR_ID: ClassVar[str] = "file_fixture_paged_rest"
    REQUIRED_KEYS: ClassVar[tuple[tuple[str, ...], ...]] = (("locator",),)

    # ``page_size`` is RETAINED (the new surface this concrete honors, vs. the
    # cursor concrete which drops it). ``cursor_token`` and ``entity_type`` are
    # dropped from PARAMS_MAPPING and rejected per-call via ``_STRIPPED_PARAMS``.
    PARAMS_MAPPING: ClassVar[dict[str, Any]] = {}

    SUPPORTED_VALUES: ClassVar[Mapping[str, frozenset[Any]]] = {
        "pagination_style": frozenset({"page"}),
    }

    @classmethod
    def _connect_from_slot(cls, slot: Mapping[str, Any]) -> Path:
        """Return the locator directory; pages are read lazily in load_data."""
        path = Path(str(slot["locator"]))
        if not path.exists():
            raise FileNotFoundError(f"{cls.CONNECTOR_ID}: locator path {path} does not exist.")
        return path

    @classmethod
    def load_data(cls, data_access: Any, features: FeatureSet) -> list[dict[str, Any]]:
        ctx = cls._prepare_load(data_access)
        path = cls._connect_from_slot(ctx.slot)

        page_size = int(ctx.slot.get("page_size", 100))
        pages_dir = path if path.is_dir() else path.parent
        page_files = sorted(pages_dir.glob("page_*.json"), key=_page_index)

        rows: list[dict[str, Any]] = []
        for page_file in page_files:
            body = load_json_fixture(cls.CONNECTOR_ID, page_file)
            results = body.get("results", [])
            for row in results:
                rows.append(copy_cached_row(row))
                if len(rows) >= ctx.result_limit:
                    return rows
            # Page-number termination: a page shorter than ``page_size`` is the
            # last page of the collection, so stop rather than reading further
            # files (mirrors how a real page-number API signals exhaustion).
            if len(results) < page_size:
                break
        return rows


class FileFixturePagedRestFeatureGroup(RestPublicFeatureGroup):
    READER_CLASS: ClassVar[type[FileFixturePagedRestReader]] = FileFixturePagedRestReader  # type: ignore[assignment]
