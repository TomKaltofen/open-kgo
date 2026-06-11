"""Universal thin FeatureGroup that delegates to a KG connector reader.

Split out of the ``kg.base`` module (which re-exports it, so import sites are
unaffected). Family bases subclass ``KgConnectorFeatureGroupBase`` and pin
``READER_CLASS``; everything else is inherited.
"""

from __future__ import annotations

from typing import Any, ClassVar

from mloda.core.abstract_plugins.components.feature_set import FeatureSet
from mloda.provider import BaseInputData, ComputeFramework, FeatureGroup

from open_kgo.compute_frameworks.python_dict_kg_framework import KgPythonDictFramework
from open_kgo.feature_groups.kg.reader_base import KgConnectorReaderBase


class KgConnectorFeatureGroupBase(FeatureGroup):
    """Universal thin FeatureGroup that delegates to a KG reader.

    Subclasses (per family) set ``READER_CLASS`` to the matching reader. The
    body is identical to ``ReadDBFeature``: ``input_data()`` returns an
    instance of ``READER_CLASS``; ``calculate_feature`` calls
    ``reader.load(features)``.

    ``compute_framework_rule`` is pinned to ``{KgPythonDictFramework}`` so the
    feature-name wrap that mloda's column-matcher needs lives in a
    framework-specific adapter rather than every reader's ``load``.
    Subclasses MUST NOT override this hook to a framework that does
    not perform an equivalent wrap: native KG rows have keys like ``s``/``p``/``o``
    that never match the user-defined feature name, so a non-wrapping framework
    silently loses every row in column slicing. If a different framework is
    truly needed, the override must point at another wrap-equivalent adapter.
    """

    READER_CLASS: ClassVar[type[KgConnectorReaderBase] | None] = None

    @classmethod
    def input_data(cls) -> BaseInputData | None:
        if cls.READER_CLASS is None:
            return None
        return cls.READER_CLASS()

    @classmethod
    def compute_framework_rule(cls) -> set[type[ComputeFramework]] | None:
        return {KgPythonDictFramework}

    @classmethod
    def calculate_feature(cls, data: Any, features: FeatureSet) -> Any:
        reader = cls.input_data()
        if reader is None:
            raise ValueError(f"{cls.__name__}.READER_CLASS is None; concrete subclasses must pin a reader.")
        return reader.load(features)
