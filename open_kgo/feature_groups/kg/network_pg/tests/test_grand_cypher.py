"""Concrete tests for GrandCypherReader.

Runs openCypher against an in-memory NetworkX graph loaded from a committed
GML fixture. Exercises the network_pg property layout against a second Cypher
engine; like Kuzu it does NOT exercise read_consistency / transaction_mode
semantics (both no-op on an embedded backend).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest

from mloda.user import Feature, Options

from open_kgo.feature_groups.kg.errors import FixtureLoadError
from open_kgo.feature_groups.kg.network_pg.grand_cypher import GrandCypherReader
from open_kgo.feature_groups.kg.network_pg.tests.kg_network_pg_contract import (
    NetworkPropertyGraphContractTestBase,
)


_FIXTURE_GML = Path(__file__).parent / "fixtures" / "org.gml"

# GML twin of org.gml with an explicit per-node ``type`` attribute, the one
# attribute the reader maps to node ``__labels__`` (see grand_cypher module
# docstring). Used to prove ``(n:Label)`` patterns match once the source
# file carries the attribute the committed fixture lacks.
_TYPED_NODES_GML = """graph [
  directed 1
  node [ id 0 label "alice" name "Alice" type "Person" ]
  node [ id 1 label "bob" name "Bob" type "Person" ]
  node [ id 2 label "acme" name "Acme" type "Company" ]
  edge [ source 0 target 1 label "MANAGES" ]
  edge [ source 0 target 2 label "WORKS_AT" ]
]
"""


class TestGrandCypherReader(NetworkPropertyGraphContractTestBase):
    @classmethod
    def connector_reader_class(cls) -> type[GrandCypherReader]:
        return GrandCypherReader

    @classmethod
    def valid_credentials(cls) -> dict[str, Any]:
        return {
            "grand_cypher": {
                "locator": str(_FIXTURE_GML),
                "dataset": "default",
                "read_consistency": "read",
                "transaction_mode": "auto",
                "result_limit": 100,
            }
        }

    @classmethod
    def invalid_credentials(cls) -> dict[str, Any]:
        # read_consistency is waived (accepted at the family-allowed set) but a
        # value OUTSIDE that set still rejects via the family enum check.
        return {"grand_cypher": {"locator": str(_FIXTURE_GML), "read_consistency": "evil"}}

    @classmethod
    def feature_under_test(cls) -> Feature:
        return Feature(
            "grand_cypher__list_names",
            options=Options(context={"query_text": "MATCH (n) RETURN n.name"}),
        )

    @classmethod
    def expected_row_shape(cls) -> Callable[[Any], bool]:
        return lambda result: isinstance(result, list) and len(result) == 3

    def test_cypher_returns_three_names(self) -> None:
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        feat = self.feature_under_test()
        rows = run_query("grand_cypher", self.valid_credentials()["grand_cypher"], feat)
        names = sorted(r["n.name"] for r in rows)
        assert names == ["Alice", "Bob", "Carol"]

    def test_directed_edge_query(self) -> None:
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        feat = Feature(
            "grand_cypher__manages",
            options=Options(context={"query_text": "MATCH (a)-[]->(b) RETURN a.name, b.name"}),
        )
        rows = run_query("grand_cypher", self.valid_credentials()["grand_cypher"], feat)
        pairs = sorted((r["a.name"], r["b.name"]) for r in rows)
        assert pairs == [("Alice", "Bob"), ("Bob", "Carol")]

    def test_result_limit_truncates_rows(self) -> None:
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        slot = dict(self.valid_credentials()["grand_cypher"])
        slot["result_limit"] = 2
        feat = self.feature_under_test()
        rows = run_query("grand_cypher", slot, feat)
        assert len(rows) == 2

    def test_typed_relationship_match_returns_pairs(self) -> None:
        """``[:MANAGES]`` matches both fixture edges via the edge-label to ``__labels__`` mapping.

        Before the mapping, grand-cypher resolved ``[:TYPE]`` against a
        ``__labels__`` attribute ``nx.read_gml`` never produces, so this
        query silently returned zero rows.
        """
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        feat = Feature(
            "grand_cypher__typed_manages",
            options=Options(context={"query_text": "MATCH (a)-[:MANAGES]->(b) RETURN a.name, b.name"}),
        )
        rows = run_query("grand_cypher", self.valid_credentials()["grand_cypher"], feat)
        pairs = sorted((r["a.name"], r["b.name"]) for r in rows)
        assert pairs == [("Alice", "Bob"), ("Bob", "Carol")]

    def test_typed_relationship_parity_with_kuzu(self, tmp_path: Path) -> None:
        """The same typed Cypher query returns the same pairs on grand-cypher and Kuzu.

        Seeds a temp Kuzu database mirroring ``org.gml`` (Alice MANAGES Bob,
        Bob MANAGES Carol) at test time, like the kuzu concrete tests, then
        runs the identical query text through both readers.
        """
        import kuzu

        # Import the sibling module so its FeatureGroup is registered even
        # when this test file runs in isolation (discovery is import-driven).
        import open_kgo.feature_groups.kg.network_pg.kuzu_cypher  # noqa: F401
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        db_path = tmp_path / "org.kuzu"
        db = kuzu.Database(str(db_path))
        conn = kuzu.Connection(db)
        conn.execute("CREATE NODE TABLE Person(name STRING, PRIMARY KEY (name))")
        conn.execute("CREATE REL TABLE MANAGES(FROM Person TO Person)")
        conn.execute("CREATE (:Person {name: 'Alice'})")
        conn.execute("CREATE (:Person {name: 'Bob'})")
        conn.execute("CREATE (:Person {name: 'Carol'})")
        conn.execute("MATCH (a:Person {name: 'Alice'}), (b:Person {name: 'Bob'}) CREATE (a)-[:MANAGES]->(b)")
        conn.execute("MATCH (b:Person {name: 'Bob'}), (c:Person {name: 'Carol'}) CREATE (b)-[:MANAGES]->(c)")
        # Release the seeding handles before the reader opens its own cached
        # Database on the same directory (kuzu locks the database dir).
        conn.close()
        db.close()

        query_text = "MATCH (a)-[:MANAGES]->(b) RETURN a.name, b.name"
        grand_feat = Feature("grand_cypher__parity", options=Options(context={"query_text": query_text}))
        grand_rows = run_query("grand_cypher", self.valid_credentials()["grand_cypher"], grand_feat)
        kuzu_feat = Feature("kuzu_cypher__parity", options=Options(context={"query_text": query_text}))
        kuzu_rows = run_query("kuzu_cypher", {"locator": str(db_path), "result_limit": 100}, kuzu_feat)

        grand_pairs = sorted((r["a.name"], r["b.name"]) for r in grand_rows)
        kuzu_pairs = sorted((r["a.name"], r["b.name"]) for r in kuzu_rows)
        assert grand_pairs == kuzu_pairs == [("Alice", "Bob"), ("Bob", "Carol")]

    def test_node_label_match_with_type_attribute(self, tmp_path: Path) -> None:
        """``(n:Label)`` matches when the GML carries the documented per-node ``type`` attribute."""
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        gml_path = tmp_path / "typed_nodes.gml"
        gml_path.write_text(_TYPED_NODES_GML, encoding="utf-8")
        slot = {"locator": str(gml_path), "result_limit": 100}

        feat = Feature(
            "grand_cypher__person_nodes",
            options=Options(context={"query_text": "MATCH (p:Person) RETURN p.name"}),
        )
        rows = run_query("grand_cypher", slot, feat)
        assert sorted(r["p.name"] for r in rows) == ["Alice", "Bob"]

        typed_feat = Feature(
            "grand_cypher__person_works_at_company",
            options=Options(context={"query_text": "MATCH (p:Person)-[:WORKS_AT]->(c:Company) RETURN p.name, c.name"}),
        )
        typed_rows = run_query("grand_cypher", slot, typed_feat)
        assert [(r["p.name"], r["c.name"]) for r in typed_rows] == [("Alice", "Acme")]

    def test_node_label_match_empty_on_committed_fixture(self) -> None:
        """Pin the documented limitation: ``org.gml`` carries no node ``type``, so node-label filters match nothing.

        The committed fixture's GML node ``label`` is consumed by
        ``nx.read_gml`` as the node id, and only a per-node ``type``
        attribute is mapped to node ``__labels__`` (see module docstring),
        so this is the documented contract rather than a silent surprise.
        """
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        feat = Feature(
            "grand_cypher__label_on_unlabeled_nodes",
            options=Options(context={"query_text": "MATCH (p:Person) RETURN p.name"}),
        )
        rows = run_query("grand_cypher", self.valid_credentials()["grand_cypher"], feat)
        assert rows == []

    def test_in_query_limit_does_not_override_result_limit(self) -> None:
        """A ``LIMIT`` inside query_text larger than ``result_limit`` must not widen the row cap.

        grand-cypher's constructor ``limit`` is overridden by an in-query
        ``LIMIT`` (verified on 1.0.x), so the reader's trailing slice is the
        actual enforcement; this test pins that the slice stays load-bearing.
        """
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        slot = dict(self.valid_credentials()["grand_cypher"])
        slot["result_limit"] = 1
        feat = Feature(
            "grand_cypher__limit_widening",
            options=Options(context={"query_text": "MATCH (n) RETURN n.name LIMIT 3"}),
        )
        rows = run_query("grand_cypher", slot, feat)
        assert len(rows) == 1

    def test_empty_locator_raises_fixture_load_error(self) -> None:
        """``locator=""`` passes the is-not-None REQUIRED_KEYS presence check but must fail loudly.

        The prior empty-graph fallback made every query against an empty
        locator silently return zero rows.
        """
        cls = self.connector_reader_class()
        creds = {cls.CONNECTOR_ID: {"locator": ""}}
        with pytest.raises(FixtureLoadError, match="missing or empty"):
            cls.connect(creds)

    def test_nonexistent_locator_raises_fixture_load_error(self, tmp_path: Path) -> None:
        """A locator pointing at a missing file raises the typed error, not raw FileNotFoundError."""
        cls = self.connector_reader_class()
        creds = {cls.CONNECTOR_ID: {"locator": str(tmp_path / "missing.gml")}}
        with pytest.raises(FixtureLoadError, match="cannot open locator file"):
            cls.connect(creds)

    def test_malformed_gml_raises_fixture_load_error(self, tmp_path: Path) -> None:
        """Unparseable GML raises the typed error, not a raw networkx exception."""
        cls = self.connector_reader_class()
        bad_path = tmp_path / "broken.gml"
        bad_path.write_text("this is not gml [[[", encoding="utf-8")
        creds = {cls.CONNECTOR_ID: {"locator": str(bad_path)}}
        with pytest.raises(FixtureLoadError, match="not parseable"):
            cls.connect(creds)
