"""SPDX SBOM parser as a code_build source, walking the dependency graph.

Second concrete in the ``code_build`` family alongside ``CycloneDxSbomReader``.
SPDX is the other major SBOM standard; its JSON form carries ``packages`` and a
``relationships`` array whose ``DEPENDS_ON`` / ``DEPENDENCY_OF`` edges form a
real dependency graph. Where the CycloneDX concrete returns a flat component
list and strips every traversal key, this concrete *honors* the family's
``TraversalMixin`` per-call keys (``lineage_direction``, ``upstream_depth``,
``downstream_depth``) by BFS-walking that graph from a starting package. It is
the family's proof that the declared traversal surface is real, not decorative.

Parsed with stdlib JSON (no new dependency), mirroring the CycloneDX concrete.
The start package is named by a concrete-local ``start_spdx_id`` per-call param
(the code_build family base has no start-node key, unlike lineage's
``asset_urn``); the family-level entity-filter keys (``entity_type``,
``relationship_type``, ``expand_paths``) are dropped and rejected per-call.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, ClassVar, Mapping

from mloda.core.abstract_plugins.components.default_options_key import DefaultOptionKeys
from mloda.core.abstract_plugins.components.feature_set import FeatureSet

from open_kgo.feature_groups.kg.base import compose_property_mapping
from open_kgo.feature_groups.kg.code_build.base import (
    CodeBuildFeatureGroup,
    CodeBuildReader,
)
from open_kgo.feature_groups.kg.fixtures import copy_cached_row, load_json_fixture
from open_kgo.feature_groups.kg.mixins import TraversalMixin


def _build_dependency_maps(
    relationships: list[Any],
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Return ``(upstream_map, downstream_map)`` from SPDX relationship records.

    ``upstream_map[p]`` lists the packages ``p`` depends on (its dependencies);
    ``downstream_map[p]`` lists the packages that depend on ``p`` (its
    dependents). Both ``DEPENDS_ON`` (``A`` depends on ``B``) and its inverse
    ``DEPENDENCY_OF`` (``B`` is a dependency of ``A``) are normalised to the
    same ``depender -> dependency`` orientation; every other relationship type
    (``CONTAINS``, ``DESCRIBES``, ...) is ignored. Malformed records missing
    either endpoint are skipped defensively.
    """
    upstream: dict[str, list[str]] = defaultdict(list)
    downstream: dict[str, list[str]] = defaultdict(list)
    for rel in relationships:
        if not isinstance(rel, dict):
            continue
        rtype = rel.get("relationshipType")
        if rtype == "DEPENDS_ON":
            depender, dependency = rel.get("spdxElementId"), rel.get("relatedSpdxElement")
        elif rtype == "DEPENDENCY_OF":
            depender, dependency = rel.get("relatedSpdxElement"), rel.get("spdxElementId")
        else:
            continue
        if not depender or not dependency:
            continue
        upstream[depender].append(dependency)
        downstream[dependency].append(depender)
    return dict(upstream), dict(downstream)


def _walk_packages(
    edge_map: dict[str, list[str]],
    packages_index: dict[str, Any],
    start: str,
    depth: int,
    remaining: int,
) -> list[dict[str, Any]]:
    """BFS along ``edge_map`` from ``start`` up to ``depth`` hops; emit package rows.

    Aborts once ``remaining`` rows have been emitted so ``result_limit`` bounds
    the work walked, not just the output sliced (mirrors the lineage readers).
    Packages are routed through ``copy_cached_row`` so the shared cached SBOM
    stays read-only when a row escapes to a caller.
    """
    if depth <= 0 or remaining <= 0:
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = {start}
    frontier: list[str] = [start]
    for _ in range(depth):
        next_frontier: list[str] = []
        for node in frontier:
            for neighbour in edge_map.get(node, []):
                if neighbour in seen:
                    continue
                seen.add(neighbour)
                # A neighbour absent from ``packages_index`` is a dangling edge:
                # it is neither emitted NOR traversed, so a real package reachable
                # only THROUGH a missing intermediate stays unreachable (the
                # "dangling edges skipped" contract covers transit nodes too).
                if neighbour in packages_index:
                    out.append(copy_cached_row(packages_index[neighbour]))
                    if len(out) >= remaining:
                        return out
                    next_frontier.append(neighbour)
        if not next_frontier:
            break
        frontier = next_frontier
    return out


class SpdxSbomReader(CodeBuildReader):
    CONNECTOR_ID: ClassVar[str] = "spdx_sbom"
    REQUIRED_KEYS: ClassVar[tuple[tuple[str, ...], ...]] = (("manifest_path", "locator"),)

    # Keep the TraversalMixin per-call keys (this concrete honors them) and add
    # a concrete-local start-node key; drop the EntityFilterParamMixin keys
    # (entity_type / relationship_type / expand_paths), which the framework then
    # rejects per-call via ``_STRIPPED_PARAMS``.
    PARAMS_MAPPING: ClassVar[dict[str, Any]] = compose_property_mapping(
        TraversalMixin.PARAMS_MAPPING_DELTA,
        {
            "start_spdx_id": {
                "explanation": "SPDXID of the package to start the dependency walk from.",
                DefaultOptionKeys.context: True,
                DefaultOptionKeys.strict_validation: False,
                DefaultOptionKeys.default: None,
            },
        },
        context="SpdxSbomReader.PARAMS_MAPPING",
    )
    REQUIRED_PARAMS: ClassVar[tuple[tuple[str, ...], ...]] = (("start_spdx_id",),)

    # SPDX relationships are a dependency graph, so the walker dispatches on
    # UPSTREAM / DOWNSTREAM / BOTH only; the family enum's Reactome-style
    # ancestors / descendants are not applicable here.
    SUPPORTED_VALUES: ClassVar[Mapping[str, frozenset[Any]]] = {
        "lineage_direction": frozenset({"UPSTREAM", "DOWNSTREAM", "BOTH"}),
    }

    @classmethod
    def _connect_from_slot(cls, slot: Mapping[str, Any]) -> dict[str, Any]:
        """Return the parsed SPDX dict; mtime-cached so repeated loads skip the JSON parse.

        Returned dict is shared across calls and MUST be treated as read-only;
        ``load_data`` routes each emitted package through ``copy_cached_row``.
        """
        manifest_path = slot.get("manifest_path") or slot.get("locator")
        return load_json_fixture(cls.CONNECTOR_ID, manifest_path)

    @classmethod
    def load_data(cls, data_access: Any, features: FeatureSet) -> list[dict[str, Any]]:
        ctx = cls._prepare_load(data_access)
        sbom = cls._connect_from_slot(ctx.slot)
        params = cls.build_params(features, ctx.slot)

        start = params.get("start_spdx_id")
        if not start:
            raise ValueError(f"{cls.CONNECTOR_ID}: 'start_spdx_id' is required.")
        direction = params.get("lineage_direction", "BOTH")
        upstream_depth = int(params.get("upstream_depth", 1))
        downstream_depth = int(params.get("downstream_depth", 0))
        result_limit = ctx.result_limit

        packages_index = {
            pkg["SPDXID"]: pkg for pkg in sbom.get("packages", []) if isinstance(pkg, dict) and "SPDXID" in pkg
        }
        upstream_map, downstream_map = _build_dependency_maps(sbom.get("relationships", []))

        rows: list[dict[str, Any]] = []
        if start in packages_index and result_limit > 0:
            rows.append(copy_cached_row(packages_index[start]))

        if direction in ("UPSTREAM", "BOTH") and len(rows) < result_limit:
            rows.extend(_walk_packages(upstream_map, packages_index, start, upstream_depth, result_limit - len(rows)))
        if direction in ("DOWNSTREAM", "BOTH") and len(rows) < result_limit:
            rows.extend(
                _walk_packages(downstream_map, packages_index, start, downstream_depth, result_limit - len(rows))
            )

        return rows


class SpdxSbomFeatureGroup(CodeBuildFeatureGroup):
    READER_CLASS: ClassVar[type[SpdxSbomReader]] = SpdxSbomReader  # type: ignore[assignment]
