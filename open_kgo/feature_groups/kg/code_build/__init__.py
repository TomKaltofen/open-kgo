"""Code / build / SBOM KG connectors (CodeQL, Bazel, CycloneDX, SPDX, ...).

Hidden-KG family. Locator is replaced by ``manifest_path`` semantics; address
includes ``commit_sha``, ``branch``, ``language_code``. Inherits ``TraversalMixin``.

DESIGN NOTE (the ``manifest_path`` vs ``locator`` asymmetry is intentional): the
other eight families address their source through the shared ``locator`` slot,
and only this family keys on ``manifest_path``. That divergence is a deliberate
demonstration that a family base may rename and enrich the address slot, not an
accidental inconsistency. ``manifest_path`` is a richer address than a bare
``locator``: the family base pairs it with ``commit_sha`` / ``branch`` /
``language_code`` slots so the address can *express* the exact source revision an
artifact was produced from, which a generic file-path locator cannot. (Those
three revision slots are reserved on the family base; the prototype readers
accept but do not yet consume them, see the PROTOTYPE NOTE below.) Generic
callers are not blocked: every concrete still accepts ``locator`` as a fallback
(the readers do ``slot.get("manifest_path") or slot.get("locator")``), so beyond
the extra revision slots the only difference is which slot name this family
documents as primary. This resolves the ``code_build``
line of the cross-family asymmetry catalog (see
``kg/tests/test_kg_catalog_declarations.py::test_cross_family_asymmetry_catalog``); it is
a recorded design decision, not an open follow-up.

PROTOTYPE NOTE: ``CycloneDxSbomReader`` reads ``manifest_path`` (with
``locator`` fallback) and returns the SBOM's ``components`` list — nothing
more. It strips the entire ``TraversalMixin`` / ``EntityFilter`` per-call
surface (rejected via ``_STRIPPED_PARAMS``); the CycloneDX ``dependencies``
array is **not walked**. ``commit_sha``, ``branch``, and ``language_code``
are accepted but unused.

SECOND CONCRETE: ``SpdxSbomReader`` *does* walk the dependency graph. It
parses the SPDX ``relationships`` array (``DEPENDS_ON`` / ``DEPENDENCY_OF``)
and honors the family's ``TraversalMixin`` keys (``lineage_direction``,
``upstream_depth``, ``downstream_depth``) by BFS from a ``start_spdx_id``,
so the family no longer inherits a traversal mixin that nothing exercises.
"""
