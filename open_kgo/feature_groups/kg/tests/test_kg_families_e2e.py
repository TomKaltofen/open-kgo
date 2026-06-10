"""Holistic end-to-end usage smoke across all 9 KG families, plus cross-family gap diagnostics.

This module is deliberately *holistic* where the rest of the suite is per-connector.
Every concrete already runs end-to-end on its own: ``kg_contract.py`` gives each of the
18 concretes an inherited ``test_calculate_feature_runs_end_to_end`` that drives the real
``mloda.run_all`` path. What did *not* exist before this module:

1. A single readable place that shows **all 9 families' usage at once** (the declarative
   ``CASES`` registry below doubles as a usage catalog: how a caller configures and queries
   each family through ``mloda.run_all``).
2. A floor that every family ships **at least two** concrete plugins. ``test_cross_group_contract``
   only floored families at >= 1 concrete each; a family silently dropping back to a single
   backend would not have tripped anything.
3. An explicit **cross-family asymmetry catalog** that surfaces the structural inconsistencies
   in the lineup (which families key on ``manifest_path`` vs ``locator``, which connector bakes
   its fixture into the reader, which one builds its backend at test time) rather than hiding them.

Gap-revealer wiring: discovery (``import_all_kg_readers`` + ``walk_subclasses``) is computed
**independently** of the ``CASES`` registry. ``test_registry_covers_all_discovered_connectors``
then asserts the two sets match, so adding a 19th connector module without a matching ``CASES``
entry turns this module red. That cross-check is the prospective gap detector; the smoke itself
is green today (all 18 work), so its value is the holistic view plus the diagnostics, not a
present-day failure.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import kuzu
import pytest

from mloda.user import Feature, Options

from open_kgo.feature_groups.kg.agent_memory.graph_walk_memory import GraphWalkMemoryReader
from open_kgo.feature_groups.kg.agent_memory.networkx_memory import NetworkxMemoryReader
from open_kgo.feature_groups.kg.base import KgConnectorReaderBase
from open_kgo.feature_groups.kg.citation_rest.file_fixture_citation import FileFixtureCitationReader
from open_kgo.feature_groups.kg.citation_rest.paginated_citation import PaginatedCitationReader
from open_kgo.feature_groups.kg.code_build.cyclonedx_sbom import CycloneDxSbomReader
from open_kgo.feature_groups.kg.code_build.spdx_sbom import SpdxSbomReader
from open_kgo.feature_groups.kg.embedded.igraph_embedded import IGraphEmbeddedReader
from open_kgo.feature_groups.kg.embedded.networkx_embedded import NetworkxEmbeddedReader
from open_kgo.feature_groups.kg.lineage.dbt_manifest import DbtManifestReader
from open_kgo.feature_groups.kg.lineage.openlineage_events import OpenLineageReader
from open_kgo.feature_groups.kg.network_pg.grand_cypher import GrandCypherReader
from open_kgo.feature_groups.kg.network_pg.kuzu_cypher import KuzuCypherReader
from open_kgo.feature_groups.kg.rdf.oxigraph_sparql import OxigraphSparqlReader
from open_kgo.feature_groups.kg.rdf.rdflib_sparql import RdfLibSparqlReader
from open_kgo.feature_groups.kg.rest_public.file_fixture_paged_rest import FileFixturePagedRestReader
from open_kgo.feature_groups.kg.rest_public.file_fixture_rest import FileFixtureRestReader
from open_kgo.feature_groups.kg.saas_authz.in_process_tuple_store import InProcessTupleStoreReader
from open_kgo.feature_groups.kg.saas_authz.paginated_tuple_store import PaginatedTupleStoreReader
from open_kgo.feature_groups.kg.tests._discovery import (
    family_of,
    family_subpackages,
    import_all_kg_readers,
    walk_subclasses,
)
from open_kgo.feature_groups.kg.tests._helpers import make_valid_credentials, run_query

# Populate KgConnectorReaderBase.__subclasses__() by walking the whole kg package.
# This is intentionally independent of the CASES registry below: it imports connector
# modules nobody added to CASES, which is exactly what the coverage cross-check needs.
import_all_kg_readers()

# open_kgo/feature_groups/kg/  (this file lives in kg/tests/)
_KG_ROOT = Path(__file__).resolve().parent.parent


def _fx(*parts: str) -> str:
    """Absolute path to a committed fixture under the kg package."""
    return str(_KG_ROOT.joinpath(*parts))


# Structural-tag vocabularies. A new connector whose shape is not one of these trips
# test_asymmetry_catalog, forcing a conscious classification rather than a silent new shape.
# _LOCATOR_KEYS doubles as the allowed vocabulary for SOURCE_SLOT declarations (None -> "baked"):
# test_source_slot_declaration_matches_catalog fails any spelling outside it (issue #21).
_INPUT_SHAPES = frozenset({"query_text", "operation", "lineage", "citation", "none"})
_LOCATOR_KEYS = frozenset({"locator", "manifest_path", "baked"})
_FIXTURE_SCOPES = frozenset({"family_tests", "baked", "built"})
_SETUPS = frozenset({"static", "build"})


def _has_keys(*keys: str) -> Callable[[dict[str, Any]], bool]:
    """Row predicate: row is a dict carrying every named key."""

    def _check(row: dict[str, Any]) -> bool:
        return isinstance(row, dict) and all(k in row for k in keys)

    return _check


@dataclass(frozen=True)
class ConnectorCase:
    """One declarative usage recipe for driving a concrete connector through mloda.run_all.

    ``make_slot`` takes a pytest ``tmp_path`` so build-at-test-time connectors (kuzu) can
    construct their backend; static connectors ignore it. The returned dict is the inner
    credentials slot (run_query wraps it as ``{connector_id: slot}``).

    The tag fields (``input_shape`` / ``locator_key`` / ``fixture_scope`` / ``setup``) are
    not used to drive the query; they exist to be aggregated by the asymmetry catalog.
    """

    family: str
    connector_id: str
    make_slot: Callable[[Path], dict[str, Any]]
    feature: Feature
    assert_row: Callable[[dict[str, Any]], bool]
    input_shape: str
    locator_key: str
    fixture_scope: str
    setup: str


def _seed_kuzu(tmp_path: Path) -> dict[str, Any]:
    """Build a throwaway Kuzu database (3 Person nodes) and return a slot pointed at it.

    This is the one connector that cannot run from a committed fixture: it needs a real
    Kuzu store on disk. tmp_path is pytest-managed, so no manual cleanup is required.
    """
    db_dir = tmp_path / "graph.kuzu"
    db = kuzu.Database(str(db_dir))
    conn = kuzu.Connection(db)
    conn.execute("CREATE NODE TABLE Person(name STRING, PRIMARY KEY (name))")
    conn.execute("CREATE (:Person {name: 'Alice'})")
    conn.execute("CREATE (:Person {name: 'Bob'})")
    conn.execute("CREATE (:Person {name: 'Carol'})")
    return make_valid_credentials(KuzuCypherReader, locator=str(db_dir))[KuzuCypherReader.CONNECTOR_ID]


def _static(reader: type[KgConnectorReaderBase], **overrides: Any) -> Callable[[Path], dict[str, Any]]:
    """Build a make_slot for a connector that reads a committed fixture (ignores tmp_path)."""

    def _make(_tmp_path: Path) -> dict[str, Any]:
        return make_valid_credentials(reader, **overrides)[reader.CONNECTOR_ID]

    return _make


_LINEAGE_WALK = {"lineage_direction": "UPSTREAM", "upstream_depth": 2, "downstream_depth": 0}


# The 9-family x 2-concrete lineup, one usage recipe each. Reading top to bottom is a tour of
# how every family is configured and queried through the same mloda.run_all entry point.
CASES: list[ConnectorCase] = [
    # network_pg -------------------------------------------------------------------------
    ConnectorCase(
        family="network_pg",
        connector_id="kuzu_cypher",
        make_slot=_seed_kuzu,
        feature=Feature(
            "kuzu_cypher__list_persons", options=Options(context={"query_text": "MATCH (p:Person) RETURN p.name"})
        ),
        assert_row=_has_keys("p.name"),
        input_shape="query_text",
        locator_key="locator",
        fixture_scope="built",
        setup="build",
    ),
    ConnectorCase(
        family="network_pg",
        connector_id="grand_cypher",
        make_slot=_static(GrandCypherReader, locator=_fx("network_pg", "tests", "fixtures", "org.gml")),
        feature=Feature("grand_cypher__list_names", options=Options(context={"query_text": "MATCH (n) RETURN n.name"})),
        assert_row=_has_keys("n.name"),
        input_shape="query_text",
        locator_key="locator",
        fixture_scope="family_tests",
        setup="static",
    ),
    # rdf --------------------------------------------------------------------------------
    ConnectorCase(
        family="rdf",
        connector_id="rdflib_sparql",
        make_slot=_static(RdfLibSparqlReader, locator=_fx("rdf", "tests", "fixtures", "sample.ttl")),
        feature=Feature(
            "rdflib_sparql__select_knows",
            options=Options(
                context={
                    "query_text": "PREFIX foaf: <http://xmlns.com/foaf/0.1/> SELECT ?s ?o WHERE { ?s foaf:knows ?o } LIMIT 10"
                }
            ),
        ),
        assert_row=_has_keys("s", "o"),
        input_shape="query_text",
        locator_key="locator",
        fixture_scope="family_tests",
        setup="static",
    ),
    ConnectorCase(
        family="rdf",
        connector_id="oxigraph_sparql",
        make_slot=_static(OxigraphSparqlReader, locator=_fx("rdf", "tests", "fixtures", "sample.ttl")),
        feature=Feature(
            "oxigraph_sparql__select_knows",
            options=Options(
                context={
                    "query_text": "PREFIX foaf: <http://xmlns.com/foaf/0.1/> SELECT ?s ?o WHERE { ?s foaf:knows ?o } LIMIT 10"
                }
            ),
        ),
        assert_row=_has_keys("s", "o"),
        input_shape="query_text",
        locator_key="locator",
        fixture_scope="family_tests",
        setup="static",
    ),
    # embedded ---------------------------------------------------------------------------
    ConnectorCase(
        family="embedded",
        connector_id="networkx_embedded",
        make_slot=_static(NetworkxEmbeddedReader, locator=_fx("embedded", "tests", "fixtures", "triangle.gml")),
        feature=Feature("networkx_embedded__nodes", options=Options(context={"operation": "nodes"})),
        assert_row=_has_keys("node"),
        input_shape="operation",
        locator_key="locator",
        fixture_scope="family_tests",
        setup="static",
    ),
    ConnectorCase(
        family="embedded",
        connector_id="igraph_embedded",
        make_slot=_static(IGraphEmbeddedReader, locator=_fx("embedded", "tests", "fixtures", "triangle.gml")),
        feature=Feature("igraph_embedded__nodes", options=Options(context={"operation": "nodes"})),
        assert_row=_has_keys("node"),
        input_shape="operation",
        locator_key="locator",
        fixture_scope="family_tests",
        setup="static",
    ),
    # rest_public ------------------------------------------------------------------------
    ConnectorCase(
        family="rest_public",
        connector_id="file_fixture_rest",
        make_slot=_static(
            FileFixtureRestReader, locator=_fx("rest_public", "tests", "fixtures"), pagination_style="cursor"
        ),
        feature=Feature("file_fixture_rest__list_works", options=Options(context={})),
        assert_row=_has_keys("id"),
        input_shape="none",
        locator_key="locator",
        fixture_scope="family_tests",
        setup="static",
    ),
    ConnectorCase(
        family="rest_public",
        connector_id="file_fixture_paged_rest",
        make_slot=_static(
            FileFixturePagedRestReader,
            locator=_fx("rest_public", "tests", "fixtures", "paged"),
            pagination_style="page",
            page_size=2,
        ),
        feature=Feature("file_fixture_paged_rest__list", options=Options(context={})),
        assert_row=_has_keys("id"),
        input_shape="none",
        locator_key="locator",
        fixture_scope="family_tests",
        setup="static",
    ),
    # lineage ----------------------------------------------------------------------------
    ConnectorCase(
        family="lineage",
        connector_id="dbt_manifest",
        make_slot=_static(DbtManifestReader, locator=_fx("lineage", "tests", "fixtures", "manifest.json")),
        feature=Feature(
            "dbt_manifest__upstream",
            options=Options(context={"asset_urn": "model.shop.fct_orders", **_LINEAGE_WALK}),
        ),
        assert_row=_has_keys("urn"),
        input_shape="lineage",
        locator_key="locator",
        fixture_scope="family_tests",
        setup="static",
    ),
    ConnectorCase(
        family="lineage",
        connector_id="openlineage_events",
        make_slot=_static(OpenLineageReader, locator=_fx("lineage", "tests", "fixtures", "openlineage_events.json")),
        feature=Feature(
            "openlineage_events__upstream",
            options=Options(context={"asset_urn": "fct_orders", **_LINEAGE_WALK}),
        ),
        assert_row=_has_keys("name"),
        input_shape="lineage",
        locator_key="locator",
        fixture_scope="family_tests",
        setup="static",
    ),
    # code_build -------------------------------------------------------------------------
    ConnectorCase(
        family="code_build",
        connector_id="cyclonedx_sbom",
        make_slot=_static(
            CycloneDxSbomReader,
            manifest_path=_fx("code_build", "tests", "fixtures", "sample.cdx.json"),
        ),
        feature=Feature("cyclonedx_sbom__components", options=Options(context={})),
        assert_row=_has_keys("name"),
        input_shape="none",
        locator_key="manifest_path",
        fixture_scope="family_tests",
        setup="static",
    ),
    ConnectorCase(
        family="code_build",
        connector_id="spdx_sbom",
        make_slot=_static(
            SpdxSbomReader,
            manifest_path=_fx("code_build", "tests", "fixtures", "sample.spdx.json"),
        ),
        feature=Feature(
            "spdx_sbom__upstream",
            options=Options(context={"start_spdx_id": "SPDXRef-Package-app", **_LINEAGE_WALK}),
        ),
        assert_row=_has_keys("name"),
        input_shape="lineage",
        locator_key="manifest_path",
        fixture_scope="family_tests",
        setup="static",
    ),
    # saas_authz -------------------------------------------------------------------------
    ConnectorCase(
        family="saas_authz",
        connector_id="in_process_tuple_store",
        make_slot=_static(
            InProcessTupleStoreReader,
            tenant="tenant_a",
            entity_type="document",
            relationship_type="viewer",
        ),
        feature=Feature("in_process_tuple_store__viewers", options=Options(context={})),
        assert_row=lambda row: isinstance(row, dict) and row.get("relation") == "viewer",
        input_shape="none",
        locator_key="baked",
        fixture_scope="baked",
        setup="static",
    ),
    ConnectorCase(
        family="saas_authz",
        connector_id="paginated_tuple_store",
        make_slot=_static(
            PaginatedTupleStoreReader,
            locator=_fx("saas_authz", "tests", "fixtures", "tuples_b.json"),
            tenant="tenant_b",
            relationship_type="viewer",
            pagination_style="cursor",
            page_size=2,
        ),
        feature=Feature("paginated_tuple_store__viewers", options=Options(context={})),
        assert_row=lambda row: isinstance(row, dict) and row.get("relation") == "viewer",
        input_shape="none",
        locator_key="locator",
        fixture_scope="family_tests",
        setup="static",
    ),
    # agent_memory -----------------------------------------------------------------------
    ConnectorCase(
        family="agent_memory",
        connector_id="networkx_memory",
        make_slot=_static(
            NetworkxMemoryReader,
            locator=_fx("agent_memory", "tests", "fixtures", "memories.json"),
            memory_scope_user_id="user_42",
            retrieval_mode="lexical",
        ),
        feature=Feature("networkx_memory__search", options=Options(context={"query_text": "coffee"})),
        assert_row=_has_keys("label"),
        input_shape="query_text",
        locator_key="locator",
        fixture_scope="family_tests",
        setup="static",
    ),
    ConnectorCase(
        family="agent_memory",
        connector_id="graph_walk_memory",
        make_slot=_static(
            GraphWalkMemoryReader,
            locator=_fx("agent_memory", "tests", "fixtures", "graph_memories.json"),
            memory_scope_user_id="user_42",
            retrieval_mode="graph",
        ),
        feature=Feature("graph_walk_memory__from_seed", options=Options(context={"query_text": "m1"})),
        assert_row=_has_keys("label"),
        input_shape="query_text",
        locator_key="locator",
        fixture_scope="family_tests",
        setup="static",
    ),
    # citation_rest ----------------------------------------------------------------------
    ConnectorCase(
        family="citation_rest",
        connector_id="file_fixture_citation",
        make_slot=_static(
            FileFixtureCitationReader,
            locator=_fx("citation_rest", "tests", "fixtures", "reactome.json"),
            species_prefix="HSA",
            dataset_version="v90",
        ),
        feature=Feature(
            "file_fixture_citation__pathway",
            options=Options(context={"stable_id": "R-HSA-1640170", "hierarchy_depth": 1}),
        ),
        assert_row=_has_keys("stableId"),
        input_shape="citation",
        locator_key="locator",
        fixture_scope="family_tests",
        setup="static",
    ),
    ConnectorCase(
        family="citation_rest",
        connector_id="paginated_citation",
        make_slot=_static(
            PaginatedCitationReader,
            locator=_fx("citation_rest", "tests", "fixtures", "citations.json"),
            pagination_style="cursor",
            page_size=2,
            species_prefix="HSA",
            dataset_version="v1",
        ),
        feature=Feature(
            "paginated_citation__page1",
            options=Options(context={"stable_id": "W1", "hierarchy_depth": 3, "entity_type": "article"}),
        ),
        assert_row=_has_keys("stableId"),
        input_shape="citation",
        locator_key="locator",
        fixture_scope="family_tests",
        setup="static",
    ),
]


_CASE_IDS = [f"{c.family}:{c.connector_id}" for c in CASES]


@pytest.mark.parametrize("case", CASES, ids=_CASE_IDS)
def test_family_usage_smoke(case: ConnectorCase, tmp_path: Path) -> None:
    """Drive each connector through the real mloda.run_all path and assert a usable row shape.

    Holistic counterpart to the per-connector ``test_calculate_feature_runs_end_to_end``:
    one sweep, all 9 families, the same DataAccessCollection -> run_all -> KgPythonDictFramework
    chain a caller uses. A regression in matching, validation, or framework adaptation that
    happens to affect every family at once shows up here as a wall of red rather than one case.
    """
    slot = case.make_slot(tmp_path)
    rows = run_query(case.connector_id, slot, case.feature)
    assert isinstance(rows, list) and len(rows) >= 1, (
        f"{case.connector_id}: expected >= 1 row from {case.feature.name!r}, got {rows!r}"
    )
    bad = [row for row in rows if not case.assert_row(row)]
    assert not bad, f"{case.connector_id}: {len(bad)} row(s) failed the shape predicate; first bad row: {bad[0]!r}"


def _is_production_connector(sub: type[KgConnectorReaderBase]) -> bool:
    """True for a shipped concrete connector, False for test-only synthetic readers.

    ``KgConnectorReaderBase.__subclasses__()`` is process-global, so by the time this
    module runs other test modules have already registered synthetic readers
    (``fake_connector_for_tests``, ``_b2_leaky_probe``, ...). Those live under a ``tests``
    package or have no real family; a production connector lives at
    ``open_kgo.feature_groups.kg.<family>.<module>`` with no ``tests`` path segment.
    Filtering on both keeps discovery to the real lineup without re-importing or
    fighting the global registry.

    Assumption: a connector lives inside a family *subpackage* (the repo convention). A concrete
    added as a bare module directly under ``kg/`` would fall outside ``family_subpackages()`` and
    escape the coverage cross-check; that layout is not used today and would surface in review.
    """
    if not sub.CONNECTOR_ID:
        return False
    if "tests" in sub.__module__.split("."):
        return False
    return family_of(sub) in family_subpackages()


def _discovered_connector_ids() -> set[str]:
    """Every shipped concrete CONNECTOR_ID, computed via discovery (independent of CASES).

    Walks the class hierarchy populated by import_all_kg_readers(), then filters to
    production connectors, so a real connector module absent from CASES still shows up
    here (the coverage cross-check can fail) while test doubles do not leak in.
    """
    return {sub.CONNECTOR_ID for sub in walk_subclasses(KgConnectorReaderBase) if _is_production_connector(sub)}


def test_registry_covers_all_discovered_connectors() -> None:
    """The CASES registry must cover exactly the concretes discovery finds: no gaps, no ghosts.

    Add a 19th connector module without a CASES entry and ``missing`` is non-empty -> red.
    This is the prospective gap detector; the smoke above only proves today's 18 work.
    """
    discovered = _discovered_connector_ids()
    registered = {c.connector_id for c in CASES}
    missing = discovered - registered
    ghosts = registered - discovered
    assert not missing, f"connectors with no end-to-end usage recipe in CASES: {sorted(missing)}"
    assert not ghosts, f"CASES entries for connector_ids that no longer exist: {sorted(ghosts)}"


def test_every_family_has_at_least_two_concretes() -> None:
    """Floor each family at >= 2 concretes. The whole premise of this branch is "two backends per base".

    ``test_cross_group_contract`` only floors at >= 1 per family; this is the >= 2 guard that
    catches a family quietly regressing to a single concrete.
    """
    by_family: dict[str, set[str]] = defaultdict(set)
    for sub in walk_subclasses(KgConnectorReaderBase):
        if not _is_production_connector(sub):
            continue
        fam = family_of(sub)
        assert fam is not None  # guaranteed by _is_production_connector; narrows for mypy
        by_family[fam].add(sub.CONNECTOR_ID)

    thin = {fam: sorted(ids) for fam, ids in by_family.items() if len(ids) < 2}
    assert not thin, f"families with fewer than two concrete plugins: {thin}"

    # Cross-check against the package layout: every connector subpackage must appear above,
    # so a family that registers zero concretes (not just < 2) is also caught.
    missing_families = family_subpackages() - set(by_family)
    assert not missing_families, f"connector subpackages registering no concrete reader: {sorted(missing_families)}"


def test_registry_tags_use_known_vocabularies() -> None:
    """Every CASES entry classifies into the known structural vocabularies.

    A connector whose invocation shape, fixture sourcing, or setup style is not one of the
    documented kinds trips this, forcing whoever adds it to extend the vocabulary consciously
    instead of introducing an unlabelled new shape that the asymmetry catalog would miss.
    """
    for case in CASES:
        assert case.input_shape in _INPUT_SHAPES, f"{case.connector_id}: unknown input_shape {case.input_shape!r}"
        assert case.locator_key in _LOCATOR_KEYS, f"{case.connector_id}: unknown locator_key {case.locator_key!r}"
        assert case.fixture_scope in _FIXTURE_SCOPES, (
            f"{case.connector_id}: unknown fixture_scope {case.fixture_scope!r}"
        )
        assert case.setup in _SETUPS, f"{case.connector_id}: unknown setup {case.setup!r}"


def _declared_locator_tag(reader: type[KgConnectorReaderBase]) -> str:
    """Map a reader's ``SOURCE_SLOT`` declaration onto the catalog's ``locator_key`` vocabulary."""
    return "baked" if reader.SOURCE_SLOT is None else reader.SOURCE_SLOT


def test_source_slot_declaration_matches_catalog() -> None:
    """Every connector's declared source slot is a known spelling, and CASES tags mirror it.

    The asserting half of issue #21 (the class-time half is
    ``KgConnectorReaderBase._validate_source_slot``). Two gates:

    1. The ``SOURCE_SLOT`` declaration of every discovered production connector
       (mapped onto the catalog vocabulary via ``None`` -> ``"baked"``) must be
       in ``_LOCATOR_KEYS``. A connector introducing a fourth spelling goes red
       here until the vocabulary is consciously extended, instead of slipping
       into the lineup unnoticed.
    2. Each ``CASES`` entry's hand-written ``locator_key`` tag must equal the
       reader's declaration, so the asymmetry catalog's locator dimension is
       checked data rather than prose a human keeps in sync.
    """
    readers_by_id = {
        sub.CONNECTOR_ID: sub for sub in walk_subclasses(KgConnectorReaderBase) if _is_production_connector(sub)
    }

    unknown = {
        connector_id: _declared_locator_tag(sub)
        for connector_id, sub in readers_by_id.items()
        if _declared_locator_tag(sub) not in _LOCATOR_KEYS
    }
    assert not unknown, (
        f"connectors declaring a SOURCE_SLOT spelling outside the known vocabulary {sorted(_LOCATOR_KEYS)}: "
        f"{unknown}. Extend _LOCATOR_KEYS consciously (and explain the new spelling in the asymmetry "
        f"catalog docstring) or align the connector with an existing slot name."
    )

    mismatched: list[str] = []
    for case in CASES:
        reader = readers_by_id.get(case.connector_id)
        if reader is None:
            # A CASES entry naming a connector discovery cannot find is a ghost;
            # test_registry_covers_all_discovered_connectors reports that
            # readably, so skip it here rather than dying on a KeyError.
            continue
        declared = _declared_locator_tag(reader)
        if case.locator_key != declared:
            mismatched.append(
                f"{case.connector_id}: CASES tags locator_key={case.locator_key!r} but the reader declares {declared!r}"
            )
    assert not mismatched, "CASES locator_key tags drifted from SOURCE_SLOT declarations:\n" + "\n".join(mismatched)


def test_cross_family_asymmetry_catalog() -> None:
    """Emit a readable catalog of where the family lineup is NOT uniform, and assert it is consistent.

    This is the diagnostic half of "reveal gaps": rather than freezing today's counts with a brittle
    ``assert build == {"kuzu_cypher"}``, it prints the asymmetries so they are visible in ``pytest -s``
    output and in any review. The only assertion guards against duplicate ``connector_id`` entries in
    ``CASES``: each case contributes exactly one tag per dimension, so a connector_id can only show up
    twice in a dimension's buckets if it was registered twice. The value here is the printed catalog,
    not a gate.

    Asymmetries surfaced (printed, not asserted):
      - ``code_build`` keys credentials on ``manifest_path`` while the other eight families use ``locator``.
        INTENTIONAL and documented (resolved per issue #18): the family base deliberately renames and
        enriches the address slot (``manifest_path`` travels with ``commit_sha`` / ``branch`` /
        ``language_code``, with ``locator`` kept as a fallback). See the DESIGN NOTE in
        ``kg/code_build/__init__.py``. It stays in the catalog so the map is complete, not because it is an
        open follow-up.
      - ``saas_authz.in_process_tuple_store`` takes no fixture credential at all: its fixture is baked into
        the reader (``_FIXTURE_PATH``), so it is the one connector you cannot repoint without code.
        INTENTIONAL and documented (resolved per issue #19): it deliberately trades a configurable
        ``locator`` for a closed, matcher-safe ``tenant`` enum, and the sibling ``paginated_tuple_store``
        is this family's configurable concrete. See ``kg/saas_authz/in_process_tuple_store.py``.
      - ``network_pg.kuzu_cypher`` is the only connector that builds its backend at test time rather than
        reading a committed fixture. INTENTIONAL and documented (resolved per issue #20): Kuzu's on-disk
        store is a binary, version-coupled format, so a committed fixture would be fragile across ``kuzu``
        upgrades; the sibling ``grand_cypher`` reads a committed ``.gml``, so the family shows both shapes.
        See the DESIGN NOTE in ``kg/network_pg/tests/test_kuzu_cypher.py``.

    Since issue #21 the ``credential locator key`` dimension is declared data, not prose: each reader
    carries a ``SOURCE_SLOT`` declaration (the "Source-slot convention" in ``kg/base.py``), enforced at
    class definition by ``_validate_source_slot`` and gated suite-wide by
    ``test_source_slot_declaration_matches_catalog`` above. This catalog keeps printing the dimension so
    the map stays complete in one place.
    """
    by_input: dict[str, list[str]] = defaultdict(list)
    by_locator: dict[str, list[str]] = defaultdict(list)
    by_scope: dict[str, list[str]] = defaultdict(list)
    by_setup: dict[str, list[str]] = defaultdict(list)
    for case in CASES:
        by_input[case.input_shape].append(case.connector_id)
        by_locator[case.locator_key].append(case.connector_id)
        by_scope[case.fixture_scope].append(case.connector_id)
        by_setup[case.setup].append(case.connector_id)

    lines = ["", "=== KG cross-family asymmetry catalog ==="]
    for title, bucket in (
        ("invocation shape", by_input),
        ("credential locator key", by_locator),
        ("fixture sourcing", by_scope),
        ("backend setup", by_setup),
    ):
        lines.append(f"\n{title}:")
        for key in sorted(bucket):
            lines.append(f"  {key:<14} ({len(bucket[key]):>2}): {', '.join(sorted(bucket[key]))}")
    print("\n".join(lines))  # captured by pytest; visible with -s or on failure

    # The one genuine invariant: no duplicate connector_id entries in CASES. Each case contributes
    # exactly one tag per dimension, so a repeated connector_id is the only way a dimension's
    # buckets can contain the same id twice.
    for dimension, bucket in (("input", by_input), ("locator", by_locator), ("scope", by_scope), ("setup", by_setup)):
        flat = [cid for ids in bucket.values() for cid in ids]
        assert len(set(flat)) == len(flat), (
            f"{dimension}: duplicate connector_id entries in CASES (a connector_id appears more than once): "
            f"{sorted(cid for cid in set(flat) if flat.count(cid) > 1)}"
        )
