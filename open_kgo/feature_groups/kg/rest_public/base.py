"""Family base for REST non-SPARQL public KG connectors."""

from __future__ import annotations

from typing import Any, ClassVar

from open_kgo.feature_groups.kg.base import (
    KgConnectorFeatureGroupBase,
    ParamReader,
    compose_property_mapping,
)
from open_kgo.feature_groups.kg.mixins import PaginationMixin
from open_kgo.feature_groups.kg.spec import property_spec


_PER_CALL_ENTITY: dict[str, Any] = {
    "entity_type": property_spec(
        "Resource type for the request (e.g. 'works', 'authors').",
    ),
}


class RestPublicReader(PaginationMixin, ParamReader):
    PROPERTY_MAPPING: ClassVar[dict[str, Any]] = compose_property_mapping(
        ParamReader.PROPERTY_MAPPING,
        PaginationMixin.PROPERTY_MAPPING_DELTA,
        {
            "dataset_version": property_spec(
                "Optional dataset/release version pin for reproducibility.",
            ),
            "user_agent": property_spec(
                "User-Agent string (often required by polite-pool endpoints).",
            ),
            "rate_limit_pace": property_spec(
                "Soft pace cap (requests/min); concrete plugin enforces.",
                default=100,
            ),
        },
        context="RestPublicReader",
    )

    PARAMS_MAPPING: ClassVar[dict[str, Any]] = compose_property_mapping(
        PaginationMixin.PARAMS_MAPPING_DELTA,
        _PER_CALL_ENTITY,
        context="RestPublicReader.PARAMS_MAPPING",
    )

    # Honest surface (option 3, see base.py): HTTP-endpoint knobs the file-fixture
    # concretes ignore (they read canned JSON from disk), reserved for a networked
    # REST concrete.
    _WAIVED_UNCONSUMED_KEYS: ClassVar[frozenset[str]] = frozenset({"dataset_version", "user_agent", "rate_limit_pace"})


class RestPublicFeatureGroup(KgConnectorFeatureGroupBase):
    READER_CLASS = None
