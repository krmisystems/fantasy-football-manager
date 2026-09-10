# Codex catalog package

The repository root contains a catalog manifest at `.codex-plugin/plugin.json`.
It uses generated copies of the skills and MCP configuration at the standard root paths.
It references the icon under `plugins/fantasy-football-manager/`.
The standalone plugin archive uses that nested directory as its root.
Both forms use the same metadata and require separately installed Python commands.

Edit the nested manifest first. Then regenerate the root manifest:

```sh
uv run python scripts/sync_catalog_manifest.py
uv run python scripts/validate_release.py
uv run python scripts/build_plugin_zip.py
```

Release validation rejects metadata differences, stale generated files, and missing icon files.
The archive builder includes only approved plugin files.
Private runtime files must remain outside either package.

The HOL Plugin Scanner workflow uses an immutable action commit and an offline scan.
It requires a score of at least 80 and rejects high-severity findings.
It does not submit data to the scanner registry or call an LLM service.
The workflow uploads its SARIF result to GitHub code scanning.
Its native static checks do not validate live ESPN behavior or replace manual review.
Optional scanner integrations can be unavailable; inspect the report for actual coverage.

Two test fixtures use explicitly fictional authentication values to verify error redaction.
Their variable names identify them as fixtures. Their redaction assertions remain in place.
The distribution workflow accepts completed main-branch runs through its trigger filter.
It also checks the source repository and event type, then checks out the fixed `refs/heads/main` ref.
It never selects a checkout ref from an incoming workflow payload.

The source plugin remains an unreleased v0.4.0 candidate.
A catalog submission or scanner pass does not publish the Python package or update Glama.
Use the [distribution check](DISTRIBUTION_STATUS.md) to verify those channels separately.
