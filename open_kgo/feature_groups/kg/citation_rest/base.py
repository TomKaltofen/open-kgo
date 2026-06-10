"""Family base for citation / scientific REST connectors."""

from __future__ import annotations

from typing import Any, ClassVar

from open_kgo.feature_groups.kg.base import (
    KgConnectorFeatureGroupBase,
    ParamReader,
    compose_property_mapping,
)
from open_kgo.feature_groups.kg.mixins import PaginationMixin
from open_kgo.feature_groups.kg.spec import property_spec


_PER_CALL_KEYS: dict[str, Any] = {
    "entity_type": property_spec(
        "Resource type (e.g. 'pathway', 'work').",
    ),
    "stable_id": property_spec(
        "System-stable identifier of the entity to fetch (e.g. R-HSA-1640170).",
    ),
    "hierarchy_depth": property_spec(
        "Depth limit for ancestors/descendants traversal.",
        default=1,
    ),
}


class CitationRestReader(PaginationMixin, ParamReader):
    PROPERTY_MAPPING: ClassVar[dict[str, Any]] = compose_property_mapping(
        ParamReader.PROPERTY_MAPPING,
        PaginationMixin.PROPERTY_MAPPING_DELTA,
        {
            "species_prefix": property_spec(
                "Species prefix (e.g. HSA for human Reactome IDs).",
            ),
            "dataset_version": property_spec(
                "Release version pin (e.g. 'v90' for Reactome).",
            ),
        },
        context="CitationRestReader",
    )

    PARAMS_MAPPING: ClassVar[dict[str, Any]] = compose_property_mapping(
        PaginationMixin.PARAMS_MAPPING_DELTA,
        _PER_CALL_KEYS,
        context="CitationRestReader.PARAMS_MAPPING",
    )

    REQUIRED_PARAMS: ClassVar[tuple[tuple[str, ...], ...]] = (("stable_id",),)

    # Honest surface (option 3, see base.py): reproducibility/scoping pins the
    # file-fixture concretes ignore (they read locator/stable_id), reserved for
    # a networked concrete.
    _WAIVED_UNCONSUMED_KEYS: ClassVar[frozenset[str]] = frozenset({"species_prefix", "dataset_version"})


class CitationRestFeatureGroup(KgConnectorFeatureGroupBase):
    READER_CLASS = None
