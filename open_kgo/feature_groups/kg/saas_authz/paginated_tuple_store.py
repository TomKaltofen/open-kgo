"""In-process tuple store that paginates results and expands group usersets.

Second concrete in the ``saas_authz`` family alongside
``InProcessTupleStoreReader`` (single-page, no expansion). This reader *honors*
the family surface the first concrete pins off: cursor pagination
(``pagination_style=cursor`` + ``page_size`` + per-call ``cursor_token``) and
``expand_paths`` (structural transitive group expansion). It is the family's
proof that the pagination + expand contract is real.

HONESTY NOTE: like the first concrete, this is a shape-only fake. It does NOT
implement real Zanzibar consistency tokens, model-id versioning, or namespaced
check evaluation; ``consistency_mode`` is accepted but not honored (waived). The
expansion is a single structural pass: a tuple whose user is a userset
reference (``group:<id>#<rel>``) is replaced by the members of that group when
``<rel>`` is listed in ``expand_paths``.

The tuples are loaded from a JSON fixture at ``locator`` (shape:
``{tenant: [[object_type, object_id, relation, user], ...]}``). An unknown
tenant raises ``UnknownTenantError`` at connect time (the agent_memory
``UnknownMemoryScopeError`` precedent), so ``tenant`` stays open (non-strict)
rather than pinned to a closed enum.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, ClassVar, Mapping

from mloda.core.abstract_plugins.components.feature_set import FeatureSet

from open_kgo.feature_groups.kg.errors import FixtureLoadError, UnknownTenantError
from open_kgo.feature_groups.kg.fixtures import load_json_fixture
from open_kgo.feature_groups.kg.mixins import parse_offset_cursor
from open_kgo.feature_groups.kg.saas_authz.base import (
    SaasAuthzFeatureGroup,
    SaasAuthzReader,
)

_Tuple = tuple[str, str, str, str]


def _validate_tuples(connector_id: str, locator: str, tenant: str, raw: Any) -> list[_Tuple]:
    """Raise ``FixtureLoadError`` unless ``raw`` is a list of 4-string tuples; return as ``list[tuple]``."""
    if not isinstance(raw, list):
        raise FixtureLoadError(
            connector_id, locator, f"tenant {tenant!r} entry must be a list, got {type(raw).__name__}."
        )
    out: list[_Tuple] = []
    for index, item in enumerate(raw):
        if not isinstance(item, list) or len(item) != 4 or not all(isinstance(s, str) for s in item):
            raise FixtureLoadError(
                connector_id,
                locator,
                f"tenant {tenant!r} index {index}: each tuple must be a list of 4 strings, got {item!r}.",
            )
        out.append((item[0], item[1], item[2], item[3]))
    return out


def _expand_usersets(rows: list[_Tuple], all_tuples: list[_Tuple], expand_paths: tuple[str, ...]) -> list[_Tuple]:
    """Replace ``group:<id>#<rel>`` users in ``rows`` with that group's members.

    The membership index is built from ``all_tuples`` (not the filtered
    ``rows``) so group-membership tuples removed by an ``entity_type`` /
    ``relationship_type`` filter are still available to resolve a userset.
    Only usersets whose ``<rel>`` is listed in ``expand_paths`` are expanded;
    everything else passes through unchanged.

    Structural-expansion semantics: an expanded userset that resolves to no
    members (an empty or absent group) yields **zero** grants — the original
    ``group:<id>#<rel>`` row is replaced by its (empty) membership, so it drops
    out of the result. A userset whose ``<rel>`` is NOT in ``expand_paths`` is
    left untouched and passes through as-is.
    """
    if not expand_paths:
        return rows
    members: dict[tuple[str, str], list[str]] = defaultdict(list)
    for object_type, object_id, relation, user in all_tuples:
        if object_type == "group":
            members[(object_id, relation)].append(user)

    expanded: list[_Tuple] = []
    for object_type, object_id, relation, user in rows:
        if user.startswith("group:") and "#" in user:
            group_ref = user[len("group:") :]
            group_id, _, group_rel = group_ref.partition("#")
            if group_rel in expand_paths:
                # dict.fromkeys dedupes members defined by repeated membership
                # tuples while preserving order, so the expansion can't emit the
                # same (object, user) grant twice.
                for member_user in dict.fromkeys(members.get((group_id, group_rel), [])):
                    expanded.append((object_type, object_id, relation, member_user))
                continue
        expanded.append((object_type, object_id, relation, user))
    return expanded


class PaginatedTupleStoreReader(SaasAuthzReader):
    CONNECTOR_ID: ClassVar[str] = "paginated_tuple_store"
    REQUIRED_KEYS: ClassVar[tuple[tuple[str, ...], ...]] = (("locator",), ("tenant",))

    # pagination_style is narrowed to the cursor style this reader implements;
    # page_size, cursor_token, and expand_paths are RETAINED (the new surface).
    SUPPORTED_VALUES: ClassVar[Mapping[str, frozenset[Any]]] = {
        "pagination_style": frozenset({"cursor"}),
    }
    # Waive consistency_mode: accepted for forward-compat but this fake
    # implements no consistency semantics (same disposition as the first
    # concrete; real SpiceDB / OpenFGA backends will dispatch on it).
    _WAIVED_ENUM_KEYS: ClassVar[frozenset[str]] = frozenset({"consistency_mode"})

    @classmethod
    def _connect_from_slot(cls, slot: Mapping[str, Any]) -> list[_Tuple]:
        locator = str(slot["locator"])
        stores = load_json_fixture(cls.CONNECTOR_ID, locator)
        tenant = str(slot["tenant"])
        if tenant not in stores:
            raise UnknownTenantError(cls.CONNECTOR_ID, tenant)
        return _validate_tuples(cls.CONNECTOR_ID, locator, tenant, stores[tenant])

    @classmethod
    def load_data(cls, data_access: Any, features: FeatureSet) -> list[dict[str, Any]]:
        ctx = cls._prepare_load(data_access)
        all_tuples = cls._connect_from_slot(ctx.slot)
        # Engages PaginationMixin._validate_cross_layer (cursor_token requires a
        # cursor-family pagination_style, which this concrete pins).
        params = cls.build_params(features, ctx.slot)

        # entity_type / relationship_type are connector defaults (slot-level).
        entity_type = ctx.slot.get("entity_type")
        relationship_type = ctx.slot.get("relationship_type")
        expand_paths = tuple(ctx.slot.get("expand_paths") or ())
        offset = parse_offset_cursor(cls.CONNECTOR_ID, params.get("cursor_token"))
        page_size = int(ctx.slot.get("page_size", 100))

        filtered = [
            t
            for t in all_tuples
            if (entity_type is None or t[0] == entity_type) and (relationship_type is None or t[2] == relationship_type)
        ]
        expanded = _expand_usersets(filtered, all_tuples, expand_paths)
        expanded.sort()

        page = expanded[offset : offset + page_size][: ctx.result_limit]
        return [{"object_type": ot, "object_id": oid, "relation": rel, "user": user} for ot, oid, rel, user in page]


class PaginatedTupleStoreFeatureGroup(SaasAuthzFeatureGroup):
    READER_CLASS: ClassVar[type[PaginatedTupleStoreReader]] = PaginatedTupleStoreReader  # type: ignore[assignment]
