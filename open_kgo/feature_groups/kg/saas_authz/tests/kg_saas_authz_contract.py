"""Per-family contract base for saas_authz connectors."""

from __future__ import annotations

from open_kgo.feature_groups.kg.tests.kg_contract import KgConnectorContractBase


class SaasAuthzContractTestBase(KgConnectorContractBase):
    def test_invalid_consistency_mode_rejected(self) -> None:
        self.assert_strict_enum_value_rejected("consistency_mode", "evil")
