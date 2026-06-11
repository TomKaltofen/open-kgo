"""SaaS / authz / wiki KG connectors (Microsoft Graph, OpenFGA, SpiceDB, Notion, ...).

Hidden-KG family. ``tenant`` instead of ``dataset`` (six observed shapes:
subdomain, instance_url, store_id, token-implicit, wiki_url, vault_path).
``consistency_token`` and ``consistency_mode`` for Zanzibar-style systems.
``expand_paths`` for OData / permission-tree expansion.

PROTOTYPE NOTE: ``InProcessTupleStoreReader`` is pinned to a canonical
``fixtures/tuples.json`` (ships ``tenant_a``); the ``locator`` slot is
dropped and ``tenant`` is a closed enum. It pins ``pagination_style=none``
and does no group expansion.

SECOND CONCRETE: ``PaginatedTupleStoreReader`` takes a configurable
``locator`` (open ``tenant``, ``UnknownTenantError`` at connect like
agent_memory) and *honors* the dropped surface: cursor pagination
(``pagination_style=cursor`` + ``page_size`` + ``cursor_token``) and
``expand_paths`` (structural ``group:<id>#<rel>`` userset expansion). Neither
concrete implements real Zanzibar consistency-token semantics;
``consistency_mode`` is waived on both.
"""
