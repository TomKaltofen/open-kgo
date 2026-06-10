"""Family base for metadata / lineage KG connectors."""

from __future__ import annotations

from typing import Any, ClassVar

from open_kgo.feature_groups.kg.base import (
    KgConnectorFeatureGroupBase,
    ParamReader,
    compose_property_mapping,
)
from open_kgo.feature_groups.kg.mixins import EntityFilterParamMixin, TraversalMixin
from open_kgo.feature_groups.kg.spec import property_spec


class LineageReader(ParamReader):
    PROPERTY_MAPPING: ClassVar[dict[str, Any]] = compose_property_mapping(
        ParamReader.PROPERTY_MAPPING,
        context="LineageReader",
    )

    PARAMS_MAPPING: ClassVar[dict[str, Any]] = compose_property_mapping(
        TraversalMixin.PARAMS_MAPPING_DELTA,
        EntityFilterParamMixin.PARAMS_MAPPING_DELTA,
        {
            "asset_urn": property_spec(
                "URN of the starting asset (DataHub/Atlas style).",
            ),
        },
        context="LineageReader.PARAMS_MAPPING",
    )

    REQUIRED_PARAMS: ClassVar[tuple[tuple[str, ...], ...]] = (("asset_urn",),)

    # Honest surface (option 3, see base.py): entity/relation filter keys (from
    # EntityFilterParamMixin) the concretes don't apply (they walk by
    # direction/depth from asset_urn), reserved for a traversal-scoping concrete.
    _WAIVED_UNCONSUMED_KEYS: ClassVar[frozenset[str]] = frozenset({"entity_type", "relationship_type", "expand_paths"})


class LineageFeatureGroup(KgConnectorFeatureGroupBase):
    READER_CLASS = None
