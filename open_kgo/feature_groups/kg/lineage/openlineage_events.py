"""OpenLineage run-event parser as a lineage source.

Second concrete in the ``lineage`` family alongside ``DbtManifestReader``.
OpenLineage is an open standard whose run events are emitted as JSON; each
event names a ``job`` plus its ``inputs`` and ``outputs`` datasets. A dataset
edge ``input -> output`` is derived per event (every input is upstream of every
output of the same run), yielding a dataset-level lineage graph we walk from a
starting ``asset_urn``. Like dbt, this is a static-artifact source (stdlib JSON,
no new dependency); it adds backend/pedigree variety on the family's
UPSTREAM / DOWNSTREAM / BOTH walk rather than a new family surface.

The fixture top level is an object ``{"events": [<run event>, ...]}`` (the
``load_json_fixture`` contract requires a dict at the top level; a bare event
array would be rejected). Datasets are identified by their ``name`` field;
``namespace`` is carried through into each row.
"""

from __future__ import annotations

from typing import Any, ClassVar, Mapping

from mloda.core.abstract_plugins.components.feature_set import FeatureSet

from open_kgo.feature_groups.kg.fixtures import load_json_fixture
from open_kgo.feature_groups.kg.lineage.base import LineageFeatureGroup, LineageReader


def _build_dataset_graph(
    events: list[Any],
) -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, str]]:
    """Return ``(upstream_map, downstream_map, namespace_index)`` from OpenLineage events.

    ``upstream_map[ds]`` is the set of datasets ``ds`` was produced from
    (parents); ``downstream_map[ds]`` is the set of datasets produced from
    ``ds`` (children). ``namespace_index`` records the first-seen namespace per
    dataset name. Malformed entries (non-dict event, non-list inputs/outputs)
    are skipped defensively: a lineage artifact assembled from many emitters
    routinely carries partial events, and one bad event should not abort the
    walk.
    """
    upstream: dict[str, set[str]] = {}
    downstream: dict[str, set[str]] = {}
    namespaces: dict[str, str] = {}

    def _register(dataset: Any) -> str | None:
        if not isinstance(dataset, dict) or "name" not in dataset:
            return None
        name = str(dataset["name"])
        if name not in namespaces:
            namespaces[name] = str(dataset.get("namespace", ""))
        return name

    for event in events:
        if not isinstance(event, dict):
            continue
        inputs = [n for n in (_register(d) for d in event.get("inputs", [])) if n is not None]
        outputs = [n for n in (_register(d) for d in event.get("outputs", [])) if n is not None]
        for out in outputs:
            for inp in inputs:
                upstream.setdefault(out, set()).add(inp)
                downstream.setdefault(inp, set()).add(out)
    return upstream, downstream, namespaces


def _walk(
    edge_map: dict[str, set[str]],
    namespaces: dict[str, str],
    start: str,
    depth: int,
    remaining: int,
) -> list[dict[str, Any]]:
    """BFS along ``edge_map`` from ``start`` up to ``depth`` hops; emit dataset rows.

    Aborts once ``remaining`` rows have been emitted so ``result_limit`` bounds
    the work walked, not just the output sliced (mirrors ``DbtManifestReader``).
    """
    if depth <= 0 or remaining <= 0:
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = {start}
    frontier: list[str] = [start]
    for _ in range(depth):
        next_frontier: list[str] = []
        for node in frontier:
            for neighbour in sorted(edge_map.get(node, set())):
                if neighbour in seen:
                    continue
                seen.add(neighbour)
                out.append({"name": neighbour, "namespace": namespaces.get(neighbour, "")})
                if len(out) >= remaining:
                    return out
                next_frontier.append(neighbour)
        if not next_frontier:
            break
        frontier = next_frontier
    return out


class OpenLineageReader(LineageReader):
    CONNECTOR_ID: ClassVar[str] = "openlineage_events"
    REQUIRED_KEYS: ClassVar[tuple[tuple[str, ...], ...]] = (("locator",),)
    # The TraversalMixin enum advertises Reactome-style ancestors / descendants
    # for citation-shaped concretes; OpenLineage events describe a dataset
    # input/output graph, so this walker dispatches on UPSTREAM / DOWNSTREAM /
    # BOTH only (same disposition as DbtManifestReader).
    SUPPORTED_VALUES: ClassVar[Mapping[str, frozenset[Any]]] = {
        "lineage_direction": frozenset({"UPSTREAM", "DOWNSTREAM", "BOTH"}),
    }

    @classmethod
    def _connect_from_slot(cls, slot: Mapping[str, Any]) -> dict[str, Any]:
        """Return the parsed events document; mtime-cached so a 100-feature run pays one parse."""
        return load_json_fixture(cls.CONNECTOR_ID, slot["locator"])

    @classmethod
    def load_data(cls, data_access: Any, features: FeatureSet) -> list[dict[str, Any]]:
        ctx = cls._prepare_load(data_access)
        document = cls._connect_from_slot(ctx.slot)
        params = cls.build_params(features, ctx.slot)

        asset_urn = params.get("asset_urn")
        if not asset_urn:
            raise ValueError(f"{cls.CONNECTOR_ID}: 'asset_urn' is required.")
        direction = params.get("lineage_direction", "BOTH")
        upstream_depth = int(params.get("upstream_depth", 1))
        downstream_depth = int(params.get("downstream_depth", 0))
        result_limit = ctx.result_limit

        events = document.get("events", [])
        upstream_map, downstream_map, namespaces = _build_dataset_graph(events)

        rows: list[dict[str, Any]] = []
        if asset_urn in namespaces and result_limit > 0:
            rows.append({"name": asset_urn, "namespace": namespaces[asset_urn]})

        if direction in ("UPSTREAM", "BOTH") and len(rows) < result_limit:
            rows.extend(_walk(upstream_map, namespaces, asset_urn, upstream_depth, result_limit - len(rows)))
        if direction in ("DOWNSTREAM", "BOTH") and len(rows) < result_limit:
            rows.extend(_walk(downstream_map, namespaces, asset_urn, downstream_depth, result_limit - len(rows)))

        return rows


class OpenLineageFeatureGroup(LineageFeatureGroup):
    READER_CLASS: ClassVar[type[OpenLineageReader]] = OpenLineageReader  # type: ignore[assignment]
