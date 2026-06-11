"""Per-family contract base for network property-graph connectors."""

from __future__ import annotations

from open_kgo.feature_groups.kg.tests.kg_contract import KgConnectorContractBase


class NetworkPropertyGraphContractTestBase(KgConnectorContractBase):
    def test_invalid_read_consistency_rejected(self) -> None:
        self.assert_strict_enum_value_rejected("read_consistency", "evil")

    def test_remote_locator_rejected(self) -> None:
        """Remote schemes must be refused, like the other file-backed readers."""
        self.assert_remote_locator_rejected("http://example.com/evil.gml")
