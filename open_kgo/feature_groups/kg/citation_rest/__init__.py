"""Citation/scientific REST connectors (Reactome, OpenAlex citation graph, ...).

A specialised flavor of REST non-SPARQL with stable_id-based addressing,
hierarchy_depth traversal, and species/release version pinning. Inherits
``PaginationMixin``.

PROTOTYPE NOTE: ``FileFixtureCitationReader`` reads ``locator``,
``stable_id``, and ``hierarchy_depth`` at runtime; it drops ``pagination_style``
/ ``page_size`` and strips ``cursor_token`` / ``entity_type``, so its ancestor
walk is bounded by ``hierarchy_depth`` alone.

SECOND CONCRETE: ``PaginatedCitationReader`` *honors* the dropped surface —
cursor pagination (``pagination_style=cursor`` + ``page_size`` + per-call
``cursor_token`` offsets) plus an ``entity_type`` filter over the citation
graph it walks. ``species_prefix`` / ``dataset_version`` remain accepted but
unused on both concretes.
"""
