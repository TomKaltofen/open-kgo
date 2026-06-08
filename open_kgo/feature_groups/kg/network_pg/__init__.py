"""Network property-graph KG connectors (Neo4j, Memgraph, Neptune-Gremlin, KuzuDB-with-Cypher, ...).

Family base for graph DBs with property-graph data model and a vendor query
language (Cypher / Gremlin / GSQL / nGQL / TypeQL). Adds ``dataset`` (database
name), ``read_consistency``, ``transaction_mode``.

PROTOTYPE NOTE: both concretes are embedded. ``KuzuCypherReader`` runs Cypher
against an embedded KuzuDB; ``GrandCypherReader`` runs openCypher against an
in-memory NetworkX graph via ``grand-cypher``. Neither has a network endpoint,
so ``read_consistency`` / ``transaction_mode`` are no-ops on both (waived for
forward-compat). The base validates property *shape* only; a second Cypher
engine on the same family base is backend variety, not new surface.
"""
