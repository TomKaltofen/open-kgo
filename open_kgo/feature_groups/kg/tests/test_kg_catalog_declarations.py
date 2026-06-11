"""Source-slot declaration gate plus the printed cross-family asymmetry catalog.

One of the three holistic modules over the shared ``_family_cases`` registry (see
that module's docstring for the split).
"""

from __future__ import annotations

from collections import defaultdict

from open_kgo.feature_groups.kg.base import KgConnectorReaderBase
from open_kgo.feature_groups.kg.tests._discovery import walk_subclasses
from open_kgo.feature_groups.kg.tests._family_cases import (
    CASES,
    LOCATOR_KEYS,
    declared_locator_tag,
    is_production_connector,
)


def test_source_slot_declaration_matches_catalog() -> None:
    """Every connector's declared source slot is a known spelling, and CASES tags mirror it.

    The asserting half of issue #21 (the class-time half is
    ``KgConnectorReaderBase._validate_source_slot``). Two gates:

    1. The ``SOURCE_SLOT`` declaration of every discovered production connector
       (mapped onto the catalog vocabulary via ``None`` -> ``"baked"``) must be
       in ``LOCATOR_KEYS``. A connector introducing a fourth spelling goes red
       here until the vocabulary is consciously extended, instead of slipping
       into the lineup unnoticed.
    2. Each ``CASES`` entry's hand-written ``locator_key`` tag must equal the
       reader's declaration, so the asymmetry catalog's locator dimension is
       checked data rather than prose a human keeps in sync.
    """
    readers_by_id = {
        sub.CONNECTOR_ID: sub for sub in walk_subclasses(KgConnectorReaderBase) if is_production_connector(sub)
    }

    unknown = {
        connector_id: declared_locator_tag(sub)
        for connector_id, sub in readers_by_id.items()
        if declared_locator_tag(sub) not in LOCATOR_KEYS
    }
    assert not unknown, (
        f"connectors declaring a SOURCE_SLOT spelling outside the known vocabulary {sorted(LOCATOR_KEYS)}: "
        f"{unknown}. Extend LOCATOR_KEYS consciously (and explain the new spelling in the asymmetry "
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
        declared = declared_locator_tag(reader)
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
