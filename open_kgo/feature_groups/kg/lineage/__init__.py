"""Metadata / lineage KG connectors (DataHub, OpenMetadata, Atlas, dbt manifest, ...).

Hidden-KG family. Locator points at a metadata service or file artifact;
``asset_urn`` is the addressing key, ``lineage_direction`` and depth properties
come from ``TraversalMixin``.

PROTOTYPE NOTE: ``DbtManifestReader`` honors ``lineage_direction`` +
``upstream_depth`` + ``downstream_depth`` (walking ``parent_map`` /
``child_map``). Across BOTH concretes, ``entity_type``, ``relationship_type``,
and ``expand_paths`` are accepted but never read (the walk is type-agnostic).

SECOND CONCRETE: ``OpenLineageReader`` walks the dataset input/output graph
derived from OpenLineage run-event JSON, honoring the same UPSTREAM /
DOWNSTREAM / BOTH directions — a second real lineage artifact on the family
base (backend variety, not new surface), with zero new dependency. It inherits
the same param surface and likewise never reads ``entity_type`` /
``relationship_type`` / ``expand_paths``.
"""
