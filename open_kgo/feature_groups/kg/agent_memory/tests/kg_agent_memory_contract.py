"""Per-family contract base for agent memory connectors.

Behavior coverage comes from the universal end-to-end test (which validates
that REQUIRED_KEYS for ``memory_scope_*`` is enforced via run_query) plus
the per-concrete ``test_lexical_search_finds_two_coffee_memories``.
"""

from __future__ import annotations

from open_kgo.feature_groups.kg.tests.kg_contract import KgConnectorContractBase


class AgentMemoryContractTestBase(KgConnectorContractBase):
    def test_remote_locator_rejected(self) -> None:
        """A ``http://``/``https://`` locator must be rejected at connect time.

        Mirrors the rdflib reader's URI-scheme guard from PR #7 so a
        copy-pasted URL surfaces as a typed ``FixtureLoadError`` instead of
        a confusing ``FileNotFoundError`` against the URL-as-relative-path.
        """
        self.assert_remote_locator_rejected("http://example.invalid/memories.json")
