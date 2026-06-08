"""Concrete tests for OxigraphSparqlReader.

Reuses the committed ``sample.ttl`` fixture (shared with the rdflib reader) so
both SPARQL engines are asserted against the same triples, demonstrating the
RDF family base generalises across implementations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest

from mloda.user import Feature, Options

from open_kgo.feature_groups.kg.errors import FixtureLoadError
from open_kgo.feature_groups.kg.rdf.oxigraph_sparql import OxigraphSparqlReader
from open_kgo.feature_groups.kg.rdf.tests.kg_rdf_contract import RdfContractTestBase


_FIXTURE_TTL = Path(__file__).parent / "fixtures" / "sample.ttl"


class TestOxigraphSparqlReader(RdfContractTestBase):
    @classmethod
    def connector_reader_class(cls) -> type[OxigraphSparqlReader]:
        return OxigraphSparqlReader

    @classmethod
    def valid_credentials(cls) -> dict[str, Any]:
        return {
            "oxigraph_sparql": {
                "locator": str(_FIXTURE_TTL),
                "result_format": "application/sparql-results+json",
                "reasoning_profile": "none",
                "result_limit": 100,
            }
        }

    @classmethod
    def invalid_credentials(cls) -> dict[str, Any]:
        # ``reasoning_profile`` is narrowed to ``{"none"}``; any other
        # family-allowed value (e.g. ``"rdfs"``) is outside the narrowed set.
        return {"oxigraph_sparql": {"locator": str(_FIXTURE_TTL), "reasoning_profile": "rdfs"}}

    @classmethod
    def feature_under_test(cls) -> Feature:
        return Feature(
            "oxigraph_sparql__select_knows",
            options=Options(
                context={
                    "query_text": (
                        "PREFIX foaf: <http://xmlns.com/foaf/0.1/> SELECT ?s ?o WHERE { ?s foaf:knows ?o } LIMIT 10"
                    ),
                }
            ),
        )

    @classmethod
    def expected_row_shape(cls) -> Callable[[Any], bool]:
        def _check(result: Any) -> bool:
            if not isinstance(result, list) or len(result) == 0:
                return False
            return all(isinstance(row, dict) and "s" in row and "o" in row for row in result)

        return _check

    def test_query_returns_three_knows_triples(self) -> None:
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        feat = self.feature_under_test()
        rows = run_query("oxigraph_sparql", self.valid_credentials()["oxigraph_sparql"], feat)
        assert len(rows) == 3

    def test_result_limit_truncates_emitted_rows(self) -> None:
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        slot = dict(self.valid_credentials()["oxigraph_sparql"])
        slot["result_limit"] = 2
        feat = self.feature_under_test()
        rows = run_query("oxigraph_sparql", slot, feat)
        assert len(rows) == 2

    def test_ask_query_returns_boolean_row(self) -> None:
        """An ASK query maps to a single ``{"boolean": ...}`` row."""
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        feat = Feature(
            "oxigraph_sparql__ask_knows",
            options=Options(
                context={
                    "query_text": "PREFIX foaf: <http://xmlns.com/foaf/0.1/> ASK { ?s foaf:knows ?o }",
                }
            ),
        )
        rows = run_query("oxigraph_sparql", self.valid_credentials()["oxigraph_sparql"], feat)
        assert rows == [{"boolean": True}]

    def test_http_locator_rejected(self) -> None:
        """connect() must refuse remote schemes (no network IO at fetch time)."""
        cls = self.connector_reader_class()
        creds = {cls.CONNECTOR_ID: {"locator": "http://example.com/evil.ttl"}}
        with pytest.raises(ValueError, match="scheme"):
            cls.connect(creds)

    def test_missing_locator_file_is_typed(self) -> None:
        """A ``locator`` pointing at a non-existent file raises ``FixtureLoadError``."""
        cls = self.connector_reader_class()
        creds = {cls.CONNECTOR_ID: {"locator": "/nonexistent/path/to/graph.ttl"}}
        with pytest.raises(FixtureLoadError):
            cls.connect(creds)

    def test_malformed_rdf_locator_is_typed(self, tmp_path: Path) -> None:
        """A present-but-unparseable Turtle file raises ``FixtureLoadError``.

        Exercises the parse-failure branch in ``load_oxigraph_store`` (pyoxigraph
        raises the builtin ``SyntaxError``, wrapped as ``FixtureLoadError``), so a
        future pyoxigraph exception-type change surfaces as a test failure rather
        than a leaked untyped error.
        """
        cls = self.connector_reader_class()
        bad = tmp_path / "bad.ttl"
        bad.write_text("@prefix ex: <http://example.org/> .\nex:s ex:p <<< not turtle", encoding="utf-8")
        creds = {cls.CONNECTOR_ID: {"locator": str(bad)}}
        with pytest.raises(FixtureLoadError):
            cls.connect(creds)
