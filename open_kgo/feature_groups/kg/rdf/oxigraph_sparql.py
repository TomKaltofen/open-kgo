"""Concrete RDF/SPARQL connector backed by an in-memory ``pyoxigraph.Store``.

Second concrete in the ``rdf`` family alongside ``RdfLibSparqlReader``: parses
a Turtle/N-Triples/RDF-XML file at ``locator`` into an embedded oxigraph store
and runs SPARQL 1.1 queries against it. oxigraph is a different SPARQL engine
(Rust-backed) than rdflib, so this proves the family base generalises across
implementations; it does not unlock new family surface (oxigraph has no RDFS
inference and we return JSON-binding-shaped rows, so ``reasoning_profile`` and
``result_format`` stay narrowed exactly as on ``RdfLibSparqlReader``).

The query text comes from the Feature's options context under ``query_text``.
``result_limit`` is enforced by breaking out of solution iteration once the cap
is reached (short-circuit, not slice-at-end). SELECT results map to
JSON-binding-shaped dicts; CONSTRUCT/DESCRIBE map to ``s``/``p``/``o`` triple
rows; ASK maps to a single ``{"boolean": ...}`` row.
"""

from __future__ import annotations

from typing import Any, ClassVar, Mapping

import pyoxigraph

from mloda.core.abstract_plugins.components.feature_set import FeatureSet

from open_kgo.feature_groups.kg.fixtures import _rejected_scheme, load_oxigraph_store
from open_kgo.feature_groups.kg.rdf.base import RdfSparqlFeatureGroup, RdfSparqlReader


class OxigraphSparqlReader(RdfSparqlReader):
    """pyoxigraph in-memory SPARQL reader.

    Accepts an optional ``locator`` (path to a turtle/n-triples/rdf-xml file).
    With ``locator=None`` the reader runs against an empty store, which is only
    useful for shape tests.
    """

    CONNECTOR_ID: ClassVar[str] = "oxigraph_sparql"
    # Strict-enum narrowings (identical disposition to RdfLibSparqlReader):
    #   - result_format: SELECT solutions are converted to JSON-binding-shaped
    #     dicts; XML / Turtle / N-Triples serialisations are not honored.
    #   - reasoning_profile: oxigraph has no inference engine, so only "none".
    SUPPORTED_VALUES: ClassVar[Mapping[str, frozenset[Any]]] = {
        "result_format": frozenset({"application/sparql-results+json"}),
        "reasoning_profile": frozenset({"none"}),
    }

    @classmethod
    def _connect_from_slot(cls, slot: Mapping[str, Any]) -> Any:
        """Return a shared, path-cached ``pyoxigraph.Store`` populated from ``slot['locator']``.

        Routes through the shared ``load_oxigraph_store`` cache (mtime-keyed)
        so a 100-feature ``mloda.run_all`` pays one parse instead of one
        hundred. The returned store is shared across calls and MUST be treated
        as read-only. ``locator=None``/falsy stays out of the cache: a fresh
        empty store is built per call, which is what the empty-store shape
        tests document. The scheme guard keeps the file-only contract (and its
        ``ValueError`` flavour) uniform with ``RdfLibSparqlReader``.
        """
        locator = slot.get("locator")
        if not locator:
            return pyoxigraph.Store()
        bad = _rejected_scheme(locator)
        if bad is not None:
            raise ValueError(
                f"{cls.CONNECTOR_ID}: locator scheme {bad!r} is not permitted; "
                f"only local file paths or file:// URLs are allowed."
            )
        return load_oxigraph_store(cls.CONNECTOR_ID, locator)

    @classmethod
    def load_data(cls, data_access: Any, features: FeatureSet) -> list[dict[str, Any]]:
        """Run the SPARQL query and return up to result_limit rows as list-of-dicts."""
        ctx = cls._prepare_load(data_access)
        store = cls._connect_from_slot(ctx.slot)

        query_text = cls.build_query(features)
        result = store.query(query_text)
        rows: list[dict[str, Any]] = []

        if isinstance(result, pyoxigraph.QuerySolutions):
            variables = result.variables
            for solution in result:
                rows.append(
                    {var.value: (solution[var].value if solution[var] is not None else None) for var in variables}
                )
                if len(rows) >= ctx.result_limit:
                    break
            return rows

        if isinstance(result, pyoxigraph.QueryBoolean):
            return [{"boolean": bool(result)}]

        # CONSTRUCT / DESCRIBE -> iterator of pyoxigraph.Triple.
        for triple in result:
            rows.append({"s": triple.subject.value, "p": triple.predicate.value, "o": triple.object.value})
            if len(rows) >= ctx.result_limit:
                break
        return rows


class OxigraphSparqlFeatureGroup(RdfSparqlFeatureGroup):
    READER_CLASS: ClassVar[type[OxigraphSparqlReader]] = OxigraphSparqlReader  # type: ignore[assignment]
