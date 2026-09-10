# Release the package

Read [distribution acceptance](DISCOVERY_ACCEPTANCE.md) for current publication status.
The records below retain their original version and validation scope.

## Published v0.3.2 evidence

Version 0.3.2 preserves a verified opponent identity when its season projection is missing.
That identity can complete draft history but cannot enter scoring or candidate selection.
The [fifth draft record](FIFTH_DRAFT_ACCEPTANCE.md) preserves the failure and direct host recovery that led to this correction.
Local checks passed 628 tests with two skips across the base suite and separate Chrome run.
All 17 isolated Chrome cases passed.

The [v0.3.2 GitHub prerelease](https://github.com/krmisystems/fantasy-football-manager/releases/tag/v0.3.2) uses commit `2810a7503073a52b4f80aacc4a35bf8d987530c5`.
All seven [source CI jobs](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34278096118) passed.
All five public asset downloads matched the reviewed hashes.

The [v0.3.2 PyPI package](https://pypi.org/project/fantasy-football-manager/0.3.2/) passed all seven checks and publication in the [approved workflow](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34278117606).
Public metadata and downloaded distributions matched the reviewed wheel and source archive.
A fresh public installation passed STDIO checks for 17 manager tools and 13 ESPN tools at 21:10:03 UTC on 2026-09-08.
Both commands reported version 0.3.2. No browser connection or live action occurred.
The first installation could not find the version in the public simple index. A fresh retry passed after the index listed it.

The [MCP Registry v0.3.2 record](https://registry.modelcontextprotocol.io/v0.1/servers/io.github.krmisystems%2Ffantasy-football-manager/versions/0.3.2) was active and latest at 21:09:50 UTC on 2026-09-08.
Exact-version and latest responses matched the reviewed metadata.
The [GitHub OIDC workflow](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34278805847) passed.

The local plugin is installed and enabled at version 0.3.2 with a Codex cachebuster.
All six installed plugin files matched the cache. The private SSH configuration remained byte-identical.
The separate server upgrade matched all 22 package files to the reviewed v0.3.2 CI wheel. Dependency versions remained unchanged.
SSH checks passed for 17 manager tools through the preserved target and 13 ESPN tools through temporary isolated state.
Both commands reported version 0.3.2. The private MCP configuration remained unchanged.
The ESPN check did not launch the preserved league target, connect a provider browser, or submit an action.
Fresh five-team Week 1 observation and current lineup calculations passed.
The [final server check](SERVER_ACCEPTANCE.md) verified ten coordinator cycles, five archive cutoffs with no missing events, and the eight-file backup.
Five SQLite integrity checks and the PostgreSQL dump catalog check passed. No new PostgreSQL restore was performed.
Live draft submission through the corrected installed v0.3.2 wheel remains **Not Tested**.
Read [distribution acceptance](DISCOVERY_ACCEPTANCE.md#version-032-distribution-checks) for artifact hashes and installation limits.

## Published v0.3.1 evidence

Version 0.3.1 fixes team-name whitespace and slash delimiters in D/ST selectors.
Its local suite passed 611 tests with two skips, including all 17 isolated Chrome cases.
The [third draft record](THIRD_DRAFT_ACCEPTANCE.md) retains the failures that led to these regressions.

The [v0.3.1 GitHub prerelease](https://github.com/krmisystems/fantasy-football-manager/releases/tag/v0.3.1) uses commit `5fd4727d0f21751508c9caac3fba62ba03c8c756`.
All seven [source CI jobs](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34262013806) passed.
All five public asset downloads matched the reviewed hashes and sizes.

The [v0.3.1 PyPI package](https://pypi.org/project/fantasy-football-manager/0.3.1/) passed the [approved publication workflow](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34262132640).
A fresh public PyPI installation passed STDIO checks for 17 manager tools and 13 ESPN tools.
Both public PyPI distribution hashes and sizes matched the reviewed build.
The first installation could not find the version in the public simple index. The same check passed after the index listed it.

The [MCP Registry v0.3.1 record](https://registry.modelcontextprotocol.io/v0.1/servers/io.github.krmisystems%2Ffantasy-football-manager/versions/0.3.1) was active and latest at the verification check.
Exact-version and latest responses matched the reviewed metadata at 18:28:25 UTC on 2026-09-08.
The [GitHub OIDC workflow](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34262942173) passed from the release commit.

The local plugin was installed and enabled at version 0.3.1 with a Codex cachebuster at this check.
All six installed plugin files matched the cache, and the private SSH configuration remained byte-identical.
After the separate server upgrade, SSH checks passed for the v0.3.1 manager and ESPN commands.
The manager used the preserved target. ESPN used temporary isolated state to avoid lifecycle writes to the running coordinator.

The [fourth draft](FOURTH_DRAFT_ACCEPTANCE.md) confirmed all 16 own selections with unchanged installed v0.3.1 execution methods.
A private launcher collected the remaining league picks. All 160 picks came from the live server browser.
One preauthorization browser error recovered without operator intervention. Live D/ST selection passed, with its exact search branch unverified.
Four teams then passed fresh Week 1 browser observation, archive cutoff checks, and backup validation.
No live server lineup swap qualified during the checked cycles. Read [server acceptance](SERVER_ACCEPTANCE.md) for the exact verification limits.
The earlier third-draft host-capture import remains a separate historical result.
See [distribution acceptance](DISCOVERY_ACCEPTANCE.md) for the complete channel checks and installation limits.

## Published v0.3.0 evidence

The [v0.3.0 GitHub release](https://github.com/krmisystems/fantasy-football-manager/releases/tag/v0.3.0) uses commit `d3acc32150ad71b0d85847f603fcd7649a2436b7`.
All seven [source CI jobs](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34197957763) passed.
All five public asset downloads matched the reviewed hashes and sizes.
The package adds the season coordinator, PostgreSQL evidence archive, and discovery measurement collector.
The [v0.3.0 PyPI package](https://pypi.org/project/fantasy-football-manager/0.3.0/) was published by the [reviewed release workflow](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34198024653).
Both public distribution hashes match the reviewed CI artifact.
All 22 wheel package files and 92 source archive files matched the release commit before approval.
The [MCP Registry v0.3.0 record](https://registry.modelcontextprotocol.io/v0.1/servers/io.github.krmisystems%2Ffantasy-football-manager/versions/0.3.0) was active and latest at publication.
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

The manual [Registry workflow](../.github/workflows/registry.yml) publishes the reviewed version from `main`.
It checks out the exact dispatch commit and validates the metadata.
It checks the public PyPI version, ownership marker, and distribution files before authentication.
It stops if that Registry version already exists or the availability check fails.
The workflow verifies the pinned publisher download against its SHA-256 digest.
It then authenticates with GitHub OIDC and publishes the staged record.
The workflow uses a temporary identity token. It does not require a stored Registry token.

For a new release, dispatch the workflow with the reviewed version after the package checks pass.
Verify the published namespace, version, and package in the Registry response.
For a later release, review the version choice and metadata digest before dispatch.
See the [official GitHub OIDC instructions](https://github.com/modelcontextprotocol/registry/blob/main/docs/modelcontextprotocol-io/github-actions.mdx).

Namespace ownership is not established by this file.
The registry contains discovery metadata; it does not host this server or its user data.
See [MCP Registry package types](https://modelcontextprotocol.io/registry/package-types) and [registry publication instructions](https://modelcontextprotocol.io/registry/quickstart).

## Evidence for live operation

Run the complete offline suite before release. Record its actual count and platform in the release notes.
Track draft and lineup acceptance separately. Require authenticated action receipts for each claimed path.
Record the installed package, private launchers, and interventions with each live result.
Isolated Chrome fixture tests verify browser mechanics without changing a real league.
Earlier direct browser picks do not establish packaged selector compatibility.
Distinguish implemented lineup automation from live acceptance testing.
The v0.4.0 candidate implements HTTP season lineups, waivers, acquisitions, drops, IR moves, and automatic week rollover.
Its privately deployed wheel has five-team read acceptance. Live writes and public release remain incomplete.
Read [HTTP season acceptance](HTTP_SEASON_ACCEPTANCE.md) for package verification and remaining gates.
Trade execution remains outside the release scope.
