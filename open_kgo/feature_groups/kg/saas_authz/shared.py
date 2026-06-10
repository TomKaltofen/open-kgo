"""Fixture-shape validation shared by the saas_authz concretes.

Both concretes load the same fixture shape
(``{tenant: [[object_type, object_id, relation, user], ...]}``) and used to
carry verbatim copies of the tuple validator (the paginated sibling's copy was
explicitly tagged "Duplicated verbatim"). The duplication made a schema change
a two-site edit; the validator now lives here as the single source of truth
for the family's tuple contract.
"""

from __future__ import annotations

from typing import Any

from open_kgo.feature_groups.kg.errors import FixtureLoadError

AuthzTuple = tuple[str, str, str, str]


def validate_tuples(connector_id: str, locator: str, tenant: str, raw: Any) -> list[AuthzTuple]:
    """Raise ``FixtureLoadError`` unless ``raw`` is a list of 4-string tuples; return as ``list[tuple]``."""
    if not isinstance(raw, list):
        raise FixtureLoadError(
            connector_id,
            locator,
            f"tenant {tenant!r} entry must be a list, got {type(raw).__name__}.",
        )
    out: list[AuthzTuple] = []
    for index, item in enumerate(raw):
        if not isinstance(item, list) or len(item) != 4 or not all(isinstance(s, str) for s in item):
            raise FixtureLoadError(
                connector_id,
                locator,
                f"tenant {tenant!r} index {index}: each tuple must be a list of 4 strings, got {item!r}.",
            )
        out.append((item[0], item[1], item[2], item[3]))
    return out
