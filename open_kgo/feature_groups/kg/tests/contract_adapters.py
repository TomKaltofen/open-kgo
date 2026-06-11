"""Adapter surface shared by every KG contract concern mixin.

The contract harness is split by concern (see ``kg_contract.py`` for the
aggregate): credential-slot validation (``contract_credentials.py``),
per-call param validation (``contract_params.py``), advertised-surface
honesty (``contract_surface.py``), and load behavior (``contract_load.py``).
Each concern mixin subclasses this ABC so it can call the 5 adapter methods
a concrete plugin's test class supplies exactly once.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable

from mloda.user import Feature

from open_kgo.feature_groups.kg.base import KgConnectorReaderBase


class KgContractAdapterBase(ABC):
    """The 5 abstract adapter methods every concrete KG plugin test implements.

    Concrete tests usually inherit them from a per-family intermediate base
    and only wire up what differs per plugin.
    """

    @classmethod
    @abstractmethod
    def connector_reader_class(cls) -> type[KgConnectorReaderBase]:
        """Return the concrete ``KgConnectorReaderBase`` subclass under test."""

    @classmethod
    @abstractmethod
    def valid_credentials(cls) -> dict[str, Any]:
        """Return a credentials dict that should match this connector.

        Shape: ``{CONNECTOR_ID: {locator: ..., ...}}``. The outer key matches
        the reader's CONNECTOR_ID; the inner dict carries all per-family +
        universal properties this concrete honors.
        """

    @classmethod
    @abstractmethod
    def invalid_credentials(cls) -> dict[str, Any]:
        """Return a credentials dict that should be rejected.

        Should violate at least one strict-validation enum (e.g. a
        ``lineage_direction="SIDEWAYS"`` for the dbt concrete, or any value
        outside the concrete's ``SUPPORTED_VALUES`` for a family-narrowed
        key), introduce an unknown closed-world key, or omit a required
        property. The earlier canonical seed was ``auth_method="evil"``;
        the auth surface was removed from the universal base, so concretes
        whose only family-level strict enum was
        ``auth_method`` now reach this contract via a closed-world
        unknown-key violation instead.
        """

    @classmethod
    @abstractmethod
    def feature_under_test(cls) -> Feature:
        """Return the canonical ``Feature`` instance for end-to-end load tests."""

    @classmethod
    @abstractmethod
    def expected_row_shape(cls) -> Callable[[Any], bool]:
        """Return a predicate that asserts the load result has the right shape."""
