"""Paginated citation connector serving a canned citation graph.

Second concrete in the ``citation_rest`` family alongside
``FileFixtureCitationReader`` (single-shot Reactome ancestor walk). This reader
*honors* the family surface the Reactome concrete drops/strips: cursor
pagination (``pagination_style=cursor`` + ``page_size`` + per-call
``cursor_token``) and the ``entity_type`` per-call filter. It models a
citation-graph API (OpenCitations / Semantic Scholar shape) where a work cites
other works via ``references``.

Walk semantics: BFS the citation graph from ``stable_id`` out to
``hierarchy_depth`` hops, optionally filter the collected works by
``entity_type``, sort by ``stableId`` for a stable page order, then return the
``page_size`` slice starting at the ``cursor_token`` offset (an
``"offset:<N>"`` token), capped at ``result_limit``. Parsed with stdlib JSON
(no new dependency).

HONESTY NOTE: the reader never emits a next-cursor; ``cursor_token`` values
are positional ``"offset:<N>"`` offsets computed by the caller, not opaque
server-issued cursors. The offset indexes into the sorted, filtered walk of
the *current* call, so changing ``entity_type`` (or the fixture contents)
between continuation calls shifts which rows a given offset returns.
"""

from __future__ import annotations

from collections import deque
from typing import Any, ClassVar, Mapping

from mloda.core.abstract_plugins.components.feature_set import FeatureSet

from open_kgo.feature_groups.kg.citation_rest.base import (
    CitationRestFeatureGroup,
    CitationRestReader,
)
from open_kgo.feature_groups.kg.errors import InvalidCredentialShape
from open_kgo.feature_groups.kg.fixtures import copy_cached_row, load_json_fixture
from open_kgo.feature_groups.kg.mixins import parse_offset_cursor, parse_page_size


class PaginatedCitationReader(CitationRestReader):
    CONNECTOR_ID: ClassVar[str] = "paginated_citation"
    REQUIRED_KEYS: ClassVar[tuple[tuple[str, ...], ...]] = (("locator",),)

    # pagination_style is narrowed to the cursor style this reader implements;
    # page_size, cursor_token, and entity_type are all RETAINED (the new surface
    # this concrete honors, vs. the Reactome concrete which drops/strips them).
    SUPPORTED_VALUES: ClassVar[Mapping[str, frozenset[Any]]] = {
        "pagination_style": frozenset({"cursor"}),
    }

    @classmethod
    def _connect_from_slot(cls, slot: Mapping[str, Any]) -> dict[str, Any]:
        """Return the parsed citation catalog; mtime-cached. Shared, read-only."""
        return load_json_fixture(cls.CONNECTOR_ID, slot["locator"])

    @classmethod
    def load_data(cls, data_access: Any, features: FeatureSet) -> list[dict[str, Any]]:
        ctx = cls._prepare_load(data_access)
        catalog = cls._connect_from_slot(ctx.slot)
        params = cls.build_params(features, ctx.slot)

        # stable_id presence is enforced by REQUIRED_PARAMS inside build_params
        # (MissingRequiredParamsError), so no None re-check is needed here.
        stable_id = params["stable_id"]
        depth = params.get("hierarchy_depth", 1)
        if isinstance(depth, bool) or not isinstance(depth, int) or depth < 0:
            raise InvalidCredentialShape(
                f"{cls.CONNECTOR_ID}: hierarchy_depth must be a non-negative int (bool not accepted), "
                f"got {type(depth).__name__} {depth!r}."
            )
        entity_type = params.get("entity_type")
        offset = parse_offset_cursor(cls.CONNECTOR_ID, params.get("cursor_token"))
        page_size = parse_page_size(cls.CONNECTOR_ID, ctx.slot.get("page_size"), 100)

        # BFS the citation graph from stable_id out to ``depth`` hops.
        collected: list[str] = []
        visited: set[str] = set()
        queue: deque[tuple[str, int]] = deque([(stable_id, 0)])
        while queue:
            node_id, hop = queue.popleft()
            if node_id in visited or node_id not in catalog:
                continue
            visited.add(node_id)
            collected.append(node_id)
            if hop < depth:
                for ref_id in catalog[node_id].get("references", []):
                    if ref_id not in visited:
                        queue.append((ref_id, hop + 1))

        # entity_type filter, then deterministic order for stable pagination.
        if entity_type is not None:
            collected = [cid for cid in collected if catalog[cid].get("entityType") == entity_type]
        collected.sort()

        # Cursor page slice, bounded by result_limit.
        page_ids = collected[offset : offset + page_size]
        return [copy_cached_row(catalog[cid]) for cid in page_ids[: ctx.result_limit]]


class PaginatedCitationFeatureGroup(CitationRestFeatureGroup):
    READER_CLASS: ClassVar[type[PaginatedCitationReader]] = PaginatedCitationReader  # type: ignore[assignment]
