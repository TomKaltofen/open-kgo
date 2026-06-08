"""Code / build / SBOM KG connectors (CodeQL, Bazel, CycloneDX, SPDX, ...).

Hidden-KG family. Locator is replaced by ``manifest_path`` semantics; address
includes ``commit_sha``, ``branch``, ``language_code``. Inherits ``TraversalMixin``.

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
