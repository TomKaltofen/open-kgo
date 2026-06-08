"""Concrete tests for SpdxSbomReader.

Unlike the CycloneDX concrete (flat component list), this reader walks the
SPDX ``DEPENDS_ON`` graph, so the tests assert the family's TraversalMixin
keys (``lineage_direction`` / ``upstream_depth`` / ``downstream_depth``) are
honored end to end.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from mloda.user import Feature, Options

from open_kgo.feature_groups.kg.code_build.spdx_sbom import SpdxSbomReader
from open_kgo.feature_groups.kg.code_build.tests.kg_code_build_contract import (
    CodeBuildContractTestBase,
)


_FIXTURE = Path(__file__).parent / "fixtures" / "sample.spdx.json"


class TestSpdxSbomReader(CodeBuildContractTestBase):
    @classmethod
    def connector_reader_class(cls) -> type[SpdxSbomReader]:
        return SpdxSbomReader

    @classmethod
    def valid_credentials(cls) -> dict[str, Any]:
        # REQUIRED_KEYS lists manifest_path / locator as alternatives; the
        # per-alternative coherence contract requires every alternative present.
        return {
            "spdx_sbom": {
                "manifest_path": str(_FIXTURE),
                "locator": str(_FIXTURE),
                "commit_sha": "a1b2c3d4",
                "branch": "main",
                "language_code": "python",
                "result_limit": 100,
            }
        }

    @classmethod
    def invalid_credentials(cls) -> dict[str, Any]:
        # No strict-validation credential enum on this concrete; trigger the
        # closed-world unknown-key rejection.
        return {"spdx_sbom": {"manifest_path": str(_FIXTURE), "definitely_not_a_kg_key": "x"}}

    @classmethod
    def feature_under_test(cls) -> Feature:
        return Feature(
            "spdx_sbom__upstream",
            options=Options(
                context={
                    "start_spdx_id": "SPDXRef-Package-app",
                    "lineage_direction": "UPSTREAM",
                    "upstream_depth": 2,
                    "downstream_depth": 0,
                }
            ),
        )

    @classmethod
    def expected_row_shape(cls) -> Callable[[Any], bool]:
        return lambda result: isinstance(result, list) and len(result) >= 1 and "name" in result[0]

    def test_upstream_walk_reaches_transitive_dependencies(self) -> None:
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        feat = self.feature_under_test()
        rows = run_query("spdx_sbom", self.valid_credentials()["spdx_sbom"], feat)
        assert {r["name"] for r in rows} == {"app", "flask", "werkzeug", "click"}

    def test_depth_one_excludes_transitive(self) -> None:
        """upstream_depth=1 stops at flask; werkzeug/click are two hops out."""
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        feat = Feature(
            "spdx_sbom__upstream_d1",
            options=Options(
                context={
                    "start_spdx_id": "SPDXRef-Package-app",
                    "lineage_direction": "UPSTREAM",
                    "upstream_depth": 1,
                    "downstream_depth": 0,
                }
            ),
        )
        rows = run_query("spdx_sbom", self.valid_credentials()["spdx_sbom"], feat)
        assert {r["name"] for r in rows} == {"app", "flask"}

    def test_downstream_walk_finds_dependents(self) -> None:
        from open_kgo.feature_groups.kg.tests._helpers import run_query

        feat = Feature(
            "spdx_sbom__downstream",
            options=Options(
                context={
                    "start_spdx_id": "SPDXRef-Package-flask",
                    "lineage_direction": "DOWNSTREAM",
                    "upstream_depth": 0,
                    "downstream_depth": 1,
                }
            ),
        )
        rows = run_query("spdx_sbom", self.valid_credentials()["spdx_sbom"], feat)
        assert {r["name"] for r in rows} == {"flask", "app"}
