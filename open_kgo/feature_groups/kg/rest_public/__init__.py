"""REST non-SPARQL public KG connectors (OpenAlex, Reactome, STRING, ConceptNet, ...).

The locator is a base URL, ``dataset`` is null (one URL is the corpus). Family
adds: ``entity_type``, ``dataset_version``, ``user_agent``, ``rate_limit_pace``.
Inherits ``PaginationMixin`` (cursor / page / cursorMark / etc.).

PROTOTYPE NOTE: both concretes walk ``page_*.json`` files on disk.
``FileFixtureRestReader`` narrows ``pagination_style`` to ``cursor`` and
terminates on ``meta.next_cursor`` (dropping ``page_size``).
``FileFixturePagedRestReader`` narrows it to ``page`` and *honors*
``page_size``, terminating when a page returns fewer than ``page_size`` rows —
so the family's counter-pagination branch is now exercised. ``rate_limit_pace``,
``user_agent``, and ``dataset_version`` remain accepted at the property layer
and never read (there is no real HTTP client to apply them to). ``entity_type``
is not a property-layer no-op: it is a per-call param that both shipped
concretes strip from ``PARAMS_MAPPING`` and therefore reject per-call (via the
``_STRIPPED_PARAMS`` hook).
"""
