"""LLM agent memory / GraphRAG KG connectors (Letta, Zep+Graphiti, Mem0, ...).

Hidden-KG family with bi-temporal semantics. Required-with-at-least-one
``memory_scope_*`` family of properties; ``valid_at_range`` /
``invalid_at_range`` / ``reference_time`` for bi-temporal queries; lexical and
graph retrieval modes are implemented (vector / hybrid remain unimplemented).

PROTOTYPE NOTE: ``NetworkxMemoryReader`` loads its in-process substrate from
a JSON fixture pointed to by the ``locator`` credential slot
(``tests/fixtures/memories.json`` ships ``user_42``). A
``memory_scope_user_id`` value absent from the fixture raises
``UnknownMemoryScopeError`` at ``connect()`` time rather than silently
returning an empty graph; an unreadable / malformed locator raises
``FixtureLoadError``. The concrete reader narrows the family-level
``REQUIRED_KEYS`` to ``("memory_scope_user_id",)`` because the fixture
format is keyed by user_id only — the other ``memory_scope_*`` aliases
live on the family base for future concrete readers (Mem0, Zep+Graphiti,
Letta) that own their own per-tenant stores.

PROTOTYPE NOTE: ``retrieval_mode`` is strict-validated against
``{lexical, vector, hybrid, graph}``. ``NetworkxMemoryReader`` narrows it to
``lexical`` (string-match over node labels); ``GraphWalkMemoryReader``
narrows it to ``graph`` (BFS from a seed node id given as ``query_text``).
``vector`` / ``hybrid`` remain unimplemented and are rejected at
``is_valid_credentials`` time via ``SUPPORTED_VALUES`` on each concrete, so
neither reader lies about what it honors.
"""
