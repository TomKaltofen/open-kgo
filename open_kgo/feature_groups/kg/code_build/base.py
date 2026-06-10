"""Family base for code / build / SBOM KG connectors."""

from __future__ import annotations

from typing import Any, ClassVar

from mloda.core.abstract_plugins.components.default_options_key import DefaultOptionKeys

from open_kgo.feature_groups.kg.base import (
    KgConnectorFeatureGroupBase,
    ParamReader,
    compose_property_mapping,
)
from open_kgo.feature_groups.kg.mixins import EntityFilterParamMixin, TraversalMixin


class CodeBuildReader(ParamReader):
    # Declared source-slot rename (issue #18, enforced per issue #21): this
    # family keys its address on manifest_path; 'locator' stays advertised as
    # a fallback. See the DESIGN NOTE in this package's __init__.py and the
    # "Source-slot convention" in kg/base.py.
    SOURCE_SLOT: ClassVar[str | None] = "manifest_path"

    PROPERTY_MAPPING: ClassVar[dict[str, Any]] = compose_property_mapping(
        ParamReader.PROPERTY_MAPPING,
        {
            "manifest_path": {
                "explanation": (
                    "Path to the manifest/database/SBOM artifact. This family deliberately keys on "
                    "manifest_path instead of the shared 'locator' slot (a richer address paired with "
                    "commit_sha/branch/language_code); 'locator' is still accepted as a fallback. See the "
                    "DESIGN NOTE in this package's __init__.py."
                ),
                DefaultOptionKeys.context: True,
                DefaultOptionKeys.strict_validation: False,
                DefaultOptionKeys.default: None,
            },
            "commit_sha": {
                "explanation": "Source commit SHA the artifact was produced from.",
                DefaultOptionKeys.context: True,
                DefaultOptionKeys.strict_validation: False,
                DefaultOptionKeys.default: None,
            },
            "branch": {
                "explanation": "Source branch the artifact was produced on.",
                DefaultOptionKeys.context: True,
                DefaultOptionKeys.strict_validation: False,
                DefaultOptionKeys.default: None,
            },
            "language_code": {
                "explanation": "Language code (e.g. 'java', 'python') for language-scoped artifacts.",
                DefaultOptionKeys.context: True,
                DefaultOptionKeys.strict_validation: False,
                DefaultOptionKeys.default: None,
            },
        },
        context="CodeBuildReader",
    )

    PARAMS_MAPPING: ClassVar[dict[str, Any]] = compose_property_mapping(
        TraversalMixin.PARAMS_MAPPING_DELTA,
        EntityFilterParamMixin.PARAMS_MAPPING_DELTA,
        context="CodeBuildReader.PARAMS_MAPPING",
    )

    # Honest surface (option 3, see base.py): VCS/build provenance the SBOM
    # concretes never consult (they parse manifest_path/locator), reserved for a
    # provenance-aware concrete.
    _WAIVED_UNCONSUMED_KEYS: ClassVar[frozenset[str]] = frozenset({"commit_sha", "branch", "language_code"})


class CodeBuildFeatureGroup(KgConnectorFeatureGroupBase):
    READER_CLASS = None
