"""Tests for the typed property-spec builder (``kg/spec.py``).

The builder's value is twofold: it emits exactly the mloda-conventional dict
shape the validators and discovery helpers read, and it rejects malformed
specs at construction time. Both halves are pinned here.
"""

from __future__ import annotations

import pytest

from mloda.core.abstract_plugins.components.default_options_key import DefaultOptionKeys

from open_kgo.feature_groups.kg.spec import PropertySpec, property_spec


class TestPropertySpecEmission:
    def test_non_strict_spec_emits_conventional_dict(self) -> None:
        """The emitted dict matches the hand-written literal shape byte-for-byte."""
        emitted = property_spec("Endpoint URL or filesystem path.", default=1000)
        assert emitted == {
            "explanation": "Endpoint URL or filesystem path.",
            DefaultOptionKeys.context: True,
            DefaultOptionKeys.strict_validation: False,
            DefaultOptionKeys.default: 1000,
        }

    def test_strict_spec_emits_allowed_values_unchanged(self) -> None:
        """``allowed_values`` passes through by reference so doc-dicts survive intact."""
        allowed = {"a": "Doc for a.", "b": "Doc for b."}
        emitted = property_spec("A strict enum.", strict=True, allowed_values=allowed, default="a")
        assert emitted["allowed_values"] is allowed
        assert emitted[DefaultOptionKeys.strict_validation] is True
        assert emitted[DefaultOptionKeys.default] == "a"

    def test_omitted_default_emits_none(self) -> None:
        """Absence of ``default`` means an explicit ``None``, matching the repo convention."""
        emitted = property_spec("An optional key.")
        assert emitted[DefaultOptionKeys.default] is None

    def test_dataclass_and_helper_agree(self) -> None:
        """``property_spec`` is exactly ``PropertySpec(...).to_mapping()``."""
        kwargs: dict[str, object] = {"strict": True, "allowed_values": {"x": "Doc."}, "default": "x"}
        assert property_spec("Same.", **kwargs) == PropertySpec("Same.", **kwargs).to_mapping()  # type: ignore[arg-type]


class TestPropertySpecInvariants:
    def test_strict_without_allowed_values_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty allowed_values"):
            property_spec("Strict but empty.", strict=True)

    def test_strict_with_empty_allowed_values_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-empty allowed_values"):
            property_spec("Strict but empty.", strict=True, allowed_values={})

    def test_allowed_values_without_strict_rejected(self) -> None:
        with pytest.raises(ValueError, match="never be"):
            property_spec("Decorative enum.", allowed_values={"a": "Doc."})

    def test_strict_default_outside_allowed_set_rejected(self) -> None:
        with pytest.raises(ValueError, match="not in the"):
            property_spec("Bad default.", strict=True, allowed_values={"a": "Doc."}, default="z")

    def test_strict_none_default_permitted(self) -> None:
        """A strict enum may leave ``default=None``; an absent key is simply not validated."""
        emitted = property_spec("Strict, no default.", strict=True, allowed_values={"a": "Doc."})
        assert emitted[DefaultOptionKeys.default] is None

    def test_iterable_allowed_values_accepted(self) -> None:
        """Plain iterables mirror ``_spec_allowed_values``; the default check still applies."""
        emitted = property_spec("Tuple enum.", strict=True, allowed_values=("a", "b"), default="b")
        assert emitted["allowed_values"] == ("a", "b")
        with pytest.raises(ValueError, match="not in the"):
            property_spec("Tuple enum.", strict=True, allowed_values=("a", "b"), default="z")

    def test_generator_allowed_values_materialized(self) -> None:
        """A one-shot iterable is materialized, not emitted exhausted (codex review finding).

        Without materialization, ``__post_init__`` consumes the generator and
        ``to_mapping`` would emit a dead iterator that behaves like an empty
        enum, silently rejecting every value downstream.
        """
        emitted = property_spec("Generator enum.", strict=True, allowed_values=(v for v in ("a", "b")), default="a")
        assert emitted["allowed_values"] == ("a", "b")
        # An exhausted-empty generator is rejected like any other empty allowed set.
        no_values: tuple[str, ...] = ()
        with pytest.raises(ValueError, match="non-empty allowed_values"):
            property_spec("Empty generator.", strict=True, allowed_values=(v for v in no_values))
