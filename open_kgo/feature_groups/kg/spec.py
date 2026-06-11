"""Typed builder for ``PROPERTY_MAPPING`` / ``PARAMS_MAPPING`` spec dicts.

mloda's property-mapping convention keeps the mapping values as plain dicts
(``FeatureGroup.PROPERTY_MAPPING`` is typed ``dict[str, Any]`` and mloda core
reads it as such; see mloda's ``docs/in_depth/property-mapping.md``), so this
module does not change what a spec IS. It changes how a spec is AUTHORED:
``PropertySpec`` validates its own invariants at construction time and then
emits the conventional dict via ``to_mapping``, so a malformed spec (a strict
enum with no ``allowed_values``, an ``allowed_values`` on a non-strict key
that would never be enforced, a strict default outside its own allowed set)
fails at import time with a named error instead of surfacing later as a
confusing validation result.

Consumers (``_validate_mapping``, ``_spec_allowed_values``, the discovery
helpers in ``tests/_discovery.py``) keep reading plain dicts; sites that
derive a spec from an existing one (e.g. ``InProcessTupleStoreReader``'s
``tenant`` override) keep using dict spreads. Only fresh literals route
through the builder.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from mloda.core.abstract_plugins.components.default_options_key import DefaultOptionKeys


@dataclass(frozen=True)
class PropertySpec:
    """One credential/param key's spec, validated at construction.

    ``allowed_values`` is usually a ``Mapping`` of value to one-line docstring
    (the shape every KG family uses); a plain iterable of values is also
    accepted, mirroring ``_spec_allowed_values``. The object passes through to
    the emitted dict unchanged so downstream readers (including
    ``bogus_value_for_strict_spec``'s ``isinstance(raw, dict)`` branch) see
    exactly what was authored.
    """

    explanation: str
    strict: bool = False
    allowed_values: Mapping[Any, str] | Iterable[Any] | None = None
    default: Any = None
    context: bool = True

    def __post_init__(self) -> None:
        if self.allowed_values is not None and not isinstance(self.allowed_values, Mapping):
            # Materialize one-shot iterables (e.g. a generator) up front: the
            # emptiness and default-membership checks below iterate the value,
            # and an exhausted iterator would otherwise be emitted into the
            # spec dict and behave like an empty enum that rejects everything.
            object.__setattr__(self, "allowed_values", tuple(self.allowed_values))
        if self.strict and not self.allowed_values:
            raise ValueError(
                f"PropertySpec({self.explanation!r}): strict=True requires a non-empty allowed_values; "
                f"a strict enum with no value space rejects everything."
            )
        if not self.strict and self.allowed_values is not None:
            raise ValueError(
                f"PropertySpec({self.explanation!r}): allowed_values without strict=True would never be "
                f"enforced by _validate_mapping; either set strict=True or drop allowed_values."
            )
        if self.strict and self.default is not None:
            allowed = (
                set(self.allowed_values.keys())
                if isinstance(self.allowed_values, Mapping)
                else set(self.allowed_values or ())
            )
            if self.default not in allowed:
                raise ValueError(
                    f"PropertySpec({self.explanation!r}): default {self.default!r} is not in the "
                    f"allowed set {sorted(allowed, key=repr)}; an omitted key would default to a "
                    f"value the validator then rejects."
                )

    def to_mapping(self) -> dict[str, Any]:
        """Emit the mloda-conventional spec dict this dataclass describes."""
        out: dict[str, Any] = {"explanation": self.explanation}
        if self.allowed_values is not None:
            out["allowed_values"] = self.allowed_values
        out[DefaultOptionKeys.context] = self.context
        out[DefaultOptionKeys.strict_validation] = self.strict
        out[DefaultOptionKeys.default] = self.default
        return out


def property_spec(
    explanation: str,
    *,
    strict: bool = False,
    allowed_values: Mapping[Any, str] | Iterable[Any] | None = None,
    default: Any = None,
    context: bool = True,
) -> dict[str, Any]:
    """Build and emit a spec dict in one expression (the common authoring case)."""
    return PropertySpec(
        explanation=explanation,
        strict=strict,
        allowed_values=allowed_values,
        default=default,
        context=context,
    ).to_mapping()
