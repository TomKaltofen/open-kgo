"""Embedded / in-memory graph KG connectors (NetworkX, igraph, KuzuDB embedded, ...).

The credential key is ``locator`` and it carries a filesystem path (no URL;
the embedded family has no network endpoint). The family base declares
``REQUIRED_KEYS = ()`` because pure object-reference cases (NetworkX object
already in memory) are valid; concrete plugins set ``REQUIRED_KEYS``
explicitly when their backend needs a path.

PROTOTYPE NOTE: two in-memory graph libraries back this family —
``NetworkxEmbeddedReader`` (``networkx``) and ``IGraphEmbeddedReader``
(``igraph``) — running the same ``nodes`` / ``edges`` / ``neighbors``
operations against the same committed GML fixtures (backend variety, not new
surface). ``read_only`` and ``max_threads`` are advisory-only on both: they
are validated at the property layer but never enforced at runtime.
"""
