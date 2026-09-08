# Release the package

Read [distribution acceptance](DISCOVERY_ACCEPTANCE.md) for current publication status.
The records below retain their original version and validation scope.

## Version 0.3.1 patch preparation

Version 0.3.1 fixes team-name whitespace and slash delimiters in D/ST selectors.
Its local suite passed 611 tests with two skips, including all 17 isolated Chrome cases.
The [third draft record](THIRD_DRAFT_ACCEPTANCE.md) retains the failures that led to these regressions.
Publication remains subject to the exact commit, CI, artifact review, and public channel checks below.

## Published v0.3.0 evidence

The [v0.3.0 GitHub release](https://github.com/krmisystems/fantasy-football-manager/releases/tag/v0.3.0) uses commit `d3acc32150ad71b0d85847f603fcd7649a2436b7`.
All seven [source CI jobs](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34197957763) passed.
All five public asset downloads matched the reviewed hashes and sizes.
The package adds the season coordinator, PostgreSQL evidence archive, and discovery measurement collector.
The [v0.3.0 PyPI package](https://pypi.org/project/fantasy-football-manager/0.3.0/) was published by the [reviewed release workflow](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34198024653).
Both public distribution hashes match the reviewed CI artifact.
All 22 wheel package files and 92 source archive files matched the release commit before approval.
The [MCP Registry v0.3.0 record](https://registry.modelcontextprotocol.io/v0.1/servers/io.github.krmisystems%2Ffantasy-football-manager/versions/0.3.0) is active and latest.
The [GitHub OIDC publication](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34199217116) passed from commit `dd5ce3a50dbc2145b8ead701e8b9ddb593d2a62c`.
See [distribution acceptance](DISCOVERY_ACCEPTANCE.md) for fresh PyPI installation and local plugin checks.

## Published v0.2.2 evidence

Version 0.2.2 includes the compatibility changes from the second live draft trial.
The local suite passed 509 tests in 31.78 seconds, including 15 isolated Chrome cases.
Read the [acceptance record](LIVE_DRAFT_ACCEPTANCE.md) for platform fallback picks, manual recovery, and runtime provenance.
Live draft source evidence does not automatically verify writes from an installed wheel.
The [v0.2.2 prerelease](https://github.com/krmisystems/fantasy-football-manager/releases/tag/v0.2.2) uses commit `b15f1a506aac83ca44365df5511fcd15b43e1d44`.
All six [release CI jobs](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34192876128) passed.
All five published asset downloads matched the verified local hashes.
The installed wheel passed both STDIO checks and an authenticated ESPN advisory monitor check.
The local plugin was installed and enabled at version 0.2.2 for that release check.
See [validation status](VALIDATION.md#published-v022-evidence) for the installation evidence and its limits.

The reusable CI workflow tests the exact requested commit before packaging.
Its browser job includes the public draft autocomplete case.
The PyPI workflow consumes those same-run artifacts after its configured publication gate.

## Historical v0.2.1 evidence

The [v0.2.1 compatibility preview](https://github.com/krmisystems/fantasy-football-manager/releases/tag/v0.2.1) is published as a prerelease.
It uses release commit `ea72798c3bb6b08bb1bcd37e82ce1cfe5fb08d36`.
All six [release CI jobs](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34186633175) passed.
All five uploaded asset downloads matched the local artifact hashes.
The installed wheel passed both STDIO checks and an authenticated ESPN connection and sync check.
The local plugin was installed and enabled at version 0.2.1. PyPI and MCP Registry publication were incomplete at that release check.
Its complete local run passed 400 tests, including 14 isolated Chrome cases.
The patch addresses weekly `columnheader` parsing, player-response request identity, selected-team lock coverage, ownership cache invalidation, and delayed navigation.
Authenticated observation, lineup calculation, and a three-poll advisory monitor passed through the development ESPN service and Chrome.
Live draft and lineup submission remain untested. No real action was submitted for this patch check.

## Published v0.2.0 baseline

The [v0.2.0 GitHub preview](https://github.com/krmisystems/fantasy-football-manager/releases/tag/v0.2.0) is published as a prerelease.
It contains the verified artifacts from commit `f9825892f4af64d7abc501e5ef15b46ef5501411`.
All six [release CI jobs](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34185668423) passed.
Version 0.2.0 is not published on PyPI or the MCP Registry. Those publication steps remain separate.
Keep the published preview artifacts unchanged. Use a new version for subsequent package changes.
Check [validation status](VALIDATION.md) before each release.

## Build the artifacts

From a clean source checkout, run:

```sh
uv sync --locked --dev
uv run pytest -q
uv run fantasy-football-manager --demo --data-dir .ci-demo
uv run fantasy-football-espn --help
uv run python scripts/validate_release.py
uv build
uv run python -m twine check "dist/*.whl" "dist/*.tar.gz"
uv run python scripts/build_plugin_zip.py
```

Twine checks the selected Python distributions only.
The ZIP builder writes a plugin archive and a SHA-256 manifest to `dist/`.
The archive includes three skills and registrations for both installed MCP commands.
It copies an explicit list of plugin files. It does not include league records or local state.

Inspect the wheel, source distribution, and plugin manifest before publication.
Do not add imports, credentials, browser profiles, databases, logs, or private captures to the release.
The local validation script checks known file types and secret patterns. It does not replace artifact review.

## Configure GitHub and PyPI

The intended repository is `krmisystems/fantasy-football-manager`.
The intended PyPI project is `fantasy-football-manager`.
Package-name availability and publisher ownership must be confirmed by the publisher account.

1. Create the PyPI project or a pending trusted publisher.
2. Set its GitHub repository to `krmisystems/fantasy-football-manager`.
3. Set its workflow filename to `release.yml`.
4. Set its environment name to `pypi`.
5. Create the `pypi` environment in GitHub.
6. Require a reviewer for that environment.
7. Confirm that the current GitHub plan enforces the environment review.
8. Set the repository variable `PYPI_PUBLISH_ENABLED` to `true` when publishing is authorized.

The release workflow runs only on manual dispatch.
It builds and tests the exact checkout before the publish job requests environment approval.
The publish job uses an OIDC identity token. It does not require a stored PyPI API token.
The workflow file cannot configure environment reviewers or create the PyPI trust relationship.
Follow the [PyPI trusted-publisher setup](https://docs.pypi.org/trusted-publishers/using-a-publisher/).

Dispatch `.github/workflows/release.yml` from the reviewed release commit.
Enter the same version as `pyproject.toml`.
Review the built artifacts before you approve the `pypi` environment.
The workflow does not create a GitHub release or publish a Codex marketplace entry.

## Register MCP metadata

The [registry template](registry/server.json) names:

- Server: `io.github.krmisystems/fantasy-football-manager`
- PyPI package: `fantasy-football-manager`
- Transport: `stdio`

The registry package describes the main `fantasy-football-manager` entry point.
The same Python distribution includes the `fantasy-football-espn` companion command.
The plugin registers both commands. A direct MCP installation must register each required server.

Publish the Python package before submitting registry metadata.
The README contains the matching `mcp-name` marker needed for PyPI package ownership checks.

The manual [Registry workflow](../.github/workflows/registry.yml) publishes the reviewed v0.3.1 record from `main`.
It checks out the exact dispatch commit and validates the metadata.
It checks the public PyPI version, ownership marker, and distribution files before authentication.
It stops if that Registry version already exists or the availability check fails.
The workflow verifies the pinned publisher download against its SHA-256 digest.
It then authenticates with GitHub OIDC and publishes the staged record.
The workflow uses a temporary identity token. It does not require a stored Registry token.

Dispatch the workflow with version `0.3.1` after the package checks pass.
Verify the published namespace, version, and package in the Registry response.
For a later release, review the version choice and metadata digest before dispatch.
See the [official GitHub OIDC instructions](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/github-actions.mdx).

Namespace ownership is not established by this file.
The registry contains discovery metadata; it does not host this server or its user data.
See [MCP Registry package types](https://modelcontextprotocol.io/registry/package-types) and [registry publication instructions](https://modelcontextprotocol.io/registry/quickstart).

## Evidence for live operation

Run the complete offline suite before release. Record its actual count and platform in the release notes.
Keep packaged live acceptance marked untested until authenticated draft and lineup actions confirm their respective full paths.
Isolated Chrome fixture tests verify browser mechanics without changing a real league.
Earlier direct browser picks do not establish packaged selector compatibility.
Distinguish implemented lineup automation from live acceptance testing.
Live waivers, acquisitions, drops, trades, and automatic week rollover remain planned.
