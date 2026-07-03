# Next major step: first public PyPI release

**Status:** proposed
**Scope:** release engineering only, no library code changes
**Package name:** `open-kgo` (unclaimed on PyPI as of 2026-07-03)

## Why this is the next step

The connector taxonomy (Layer 1) and SemanticField scoring (Layer 2) are built and
merged. Layer 3 (Discovery Engine) continues on its own track. The biggest gap for
the project as a whole is no longer a missing feature, it is distribution:

- The repo is public, but the only way to use it is to clone it and run
  `uv sync --extra kg-all`. There is no `pip install open-kgo`.
- A published package is the prerequisite for listing open-kgo in
  [mloda-registry](https://github.com/mloda-ai/mloda-registry) so it can be
  discovered alongside the other mloda plugins.
- PyPI is also the only way to get real adoption signals (download stats,
  dependent packages) instead of GitHub stars alone.

Almost all of the machinery already exists in the repo; what is missing is a small
set of one-time bootstrap actions plus a handful of pre-release decisions.

## What is already in place

| Piece | Where | State |
|---|---|---|
| Packaging metadata (PEP 639 license, classifiers, `py.typed`, URLs) | `pyproject.toml` | Done |
| Per-family extras scheme (`kg-rdf`, ..., `kg-all`, `demo`) | `pyproject.toml` | Done |
| Version bump + tagging + GitHub release via semantic-release | `.releaserc.yaml` | Done, never run |
| Release workflow with a PyPI publish job (`build` + `twine upload`) | `.github/workflows/release.yaml` | Done, never run |
| Quality gate (pytest, ruff, mypy strict, bandit) | `tox.ini`, `.github/workflows/test.yml` | Done, green |

## What is missing

1. **Bootstrap tag.** `.releaserc.yaml` uses `tagFormat: ${version}` and
   `pyproject.toml` notes that semantic-release needs a `0.2.0` tag pushed once by
   hand. No tag exists yet. The tag must point at the commit that set
   `version = "0.2.0"` (`84c54a5`, the repo bootstrap), so that the `feat:`
   commits merged since then are picked up and the first computed release is
   `0.3.0`. Tagging current `main` as `0.2.0` instead would make semantic-release
   report "no new version" and the publish job would never fire.
2. **PyPI credentials.** The publish job reads `secrets.PYPI_API_TOKEN`, which is
   not set. Either create the token and secret, or (preferred, one-time setup of
   similar size) switch the job to
   [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/) with
   `pypa/gh-action-pypi-publish` and drop the long-lived token entirely.
3. **Wheel contents decision.** `[tool.setuptools.packages.find]` includes
   `open_kgo*`, which pulls every `tests/` subpackage (the in-repo contract
   harness) into the wheel, while `package-data` ships only `py.typed`, so the
   test fixtures those tests need would be missing. Either exclude `*.tests*`
   from the wheel (smaller, honest artifact) or ship fixtures too. Excluding is
   recommended; the harness is explicitly not published for external reuse.
4. **Runtime dependency check.** `mloda-testing>=0.3.1` is currently a hard
   runtime dependency. If it is only needed by the test harness, move it to the
   `dev` extra before the first release so downstream installs stay lean.
5. **Name confirmation.** `open-kgo` is unclaimed on PyPI (checked 2026-07-03).
   If a `mloda-*` namespace decision is pending, it must land before the first
   upload, because a published name is permanent.
6. **Verification pass.** TestPyPI upload first, then a clean-venv smoke test:
   `pip install "open-kgo[kg-all]"` followed by the README quickstart.

## Release runbook

1. Resolve decisions 3 to 5 above (small PRs where needed).
2. Configure PyPI publishing (secret or Trusted Publisher) on
   `mloda-ai/open-kgo`.
3. Push the bootstrap tag: `git tag 0.2.0 84c54a5` and `git push origin 0.2.0`.
4. Dry-run against TestPyPI: `python -m build`, then
   `twine upload --repository testpypi dist/*`, then install from TestPyPI into a
   clean venv and run the README quickstart.
5. Trigger the `Release` workflow (`workflow_dispatch` on `main`). It computes
   the next version from the conventional commits since `0.2.0` (expected:
   `0.3.0`), updates `pyproject.toml` and `uv.lock`, tags, creates the GitHub
   release, and uploads the sdist and wheel to PyPI.
6. Post-release: verify `pip install "open-kgo[kg-all]"` from PyPI in a clean
   venv, add a pip-based install path to the README quickstart, and open the
   mloda-registry listing PR.

## Definition of done

- `open-kgo` installable from PyPI with all extras resolving.
- GitHub release and matching git tag created by the pipeline, not by hand.
- README quickstart works from a pip install without cloning the repo.
- open-kgo listed (or listing PR open) in mloda-registry.

## Out of scope

- Layer 3 Discovery Engine (continues separately on the SemanticField track).
- New connector families or concrete plugins.
- Extracting the test contract harness into a published package (deliberately
  deferred; see `open_kgo/feature_groups/kg/README.md`).
