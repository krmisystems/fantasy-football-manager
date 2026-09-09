# Validation status

Version 0.3.0 adds a server coordinator and labeled evidence archive.
Read [server acceptance](SERVER_ACCEPTANCE.md) for current tests, team observations, backup recovery, and verification limits.
Read [distribution acceptance](DISCOVERY_ACCEPTANCE.md) for the completed discovery findings and public channel checks.
The historical results below retain their original runtime scope.

## Version 0.3.3 tool definitions

Version 0.3.3 describes all input parameters across 17 manager tools and 13 ESPN companion tools.
It adds structured snapshot, configuration, and action payload schemas.
Existing tool names, defaults, accepted calls, and execution policy remain unchanged.
Behavior annotations now describe persistent local writes and worker effects more accurately.
These annotations can change how MCP clients display approval requests.

The final base local run passed **647 tests with 19 skips in 18.77 seconds**.
The separate isolated Chrome run passed **17 tests in 20.07 seconds**.
Combined, these runs passed **664 tests**. The two remaining skips require PostgreSQL configuration and Windows symlink privileges.
The new cases cover emitted MCP schemas, representative calls, revision conflicts, proposal replay, evidence writes, and mocked ESPN delegation.
These tests did not submit a live ESPN action or upgrade the running season service.
All seven [source CI jobs](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34314653579) passed for commit `f04710724a52ef0a2da35795ca27b00eda37b0f3`.
A fresh public PyPI installation matched all 23 package files to the reviewed wheel.
Its actual STDIO definitions matched the final export for all 30 tools, and both empty-state read-only checks passed.
The installed CLI demo returned `status="ok"`, `live_actions=false`, and the same fictional 5.50-point improvement.
Public distribution and external TDQS status are tracked in the [tool definition review](TOOL_DEFINITION_QUALITY.md).

## Version 0.3.2 source checks and fifth draft

Version 0.3.2 separates verified opponent identity from season projection availability.
An opponent draft selection can retain `projection=None` when its identity and owner are verified.
The engine counts that player's position and roster occupancy. It excludes the player from scoring and recommendation pools.
Available and selected-team players still require season projections. Ambiguous identity and incorrect ownership still block the snapshot.
The manager capability response links to the versioned compatibility report.
This replaces the single `pending` acceptance label without granting additional execution capabilities.

The [parser tests](../tests/test_espn_data.py) cover API, Activity, plain history, and accessibility history inputs.
They also cover absent records, empty statistics, preserved projection timestamps, and a complete 160-pick replay.
The [engine tests](../tests/test_draft.py) verify roster caps, excluded scoring inputs, and blocked rankings without weekly evidence.
The base local run passed **611 tests with 19 skips in 17.46 seconds**.
The separate Chrome integration run passed **17 tests in 19.59 seconds**.
Combined, these runs passed **628 tests**, with two remaining skips for PostgreSQL configuration and Windows symlink privileges.
All seven [source CI jobs](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34278096118) passed for commit `2810a7503073a52b4f80aacc4a35bf8d987530c5`.
This includes Windows and Ubuntu on Python 3.11 and 3.14, Chrome, PostgreSQL, and package checks.
No live draft used version 0.3.2. Its tests do not establish installed-wheel live submission acceptance.

The [fifth draft](FIFTH_DRAFT_ACCEPTANCE.md) used unchanged installed v0.3.1 execution methods and a private orchestration launcher.
An empty opponent projection blocked history after 132 stored picks.
The operator stopped the worker with zero unresolved claims before entering the separate browser.
The roster completed with **13 manager-confirmed picks, two direct host-browser picks, and one unattributed selection**.
Autopick was off before and after both direct clicks. No evidence establishes the executor of pick 135.

The final host capture contains **160 ordered selections and all 16 own picks**.
Private checks matched every row's identity, position, NFL team, and snake-order owner.
All 132 stored picks matched the capture. The existing 501 player records remained unchanged during comparison.
The reviewed v0.3.2 runtime imported the full history with provider `espn_host_browser_reconciliation`.
The import retained the original host observation time and selection attribution. It did not grant permission for a live draft action.
The private recovery and activation helpers passed 57 isolated checks and independent review.
Read [server acceptance](SERVER_ACCEPTANCE.md) for the separate fresh Week 1 handoff.
Its final check passed after ten coordinator cycles, with five current lineup calculations, zero unresolved claims, five complete archive cutoffs, and an eight-file backup.
This trial required recovery and does not establish unattended draft completion.

The frozen manager record contains **1,124 completed, accepted calls and 44,960 completed trials**.
All calls have disposition `current`, with zero discarded calls and zero excluded records.
The 13 manager receipt intervals range from **1.323 to 3.500 seconds**, with a **2.449-second median**.
These intervals measure authorization to platform observation. They exclude the separate host clicks and do not establish a general latency bound.

## Version 0.3.1 source checks

Version 0.3.1 fixes team-name whitespace and slash delimiters in D/ST browser selectors.
The complete Windows suite passed **611 tests with two skips in 35.63 seconds**, including all **17 Chrome cases**.
The skips required PostgreSQL configuration and Windows symlink privileges.
Both D/ST display variants failed before the selector fix and passed afterward.
The [third draft acceptance record](THIRD_DRAFT_ACCEPTANCE.md) preserves the live failures, platform fallbacks, and operator interventions.
That trial used installed v0.3.0 with private runtime changes. It does not verify live execution of the corrected v0.3.1 source.
Check [distribution acceptance](DISCOVERY_ACCEPTANCE.md) for publication and installation status.

## Fourth live draft: Verified installed v0.3.1 execution

The [fourth draft acceptance record](FOURTH_DRAFT_ACCEPTANCE.md) verifies all **160 league picks and 16 manager-confirmed selections**.
The run recorded **zero ESPN Autopicks and zero host-browser `DRAFT` clicks**.
All 22 installed package files matched the reviewed v0.3.1 wheel from commit `5fd4727d0f21751508c9caac3fba62ba03c8c756`.
The installed execution methods remained unchanged. A private orchestration launcher handled collection and lifecycle.
No package patch, restart, or manual recovery was required during the run.

One `browser_control` error occurred before authorization at the first turn.
Its exact text was unavailable. A later check recovered before submission.
A live Ravens D/ST selection succeeded.
The record does not establish that the exact D/ST autocomplete branch ran.

The durable calculation record contains **1,073 accepted calls and 42,920 completed trials**.
The 16 authorization-to-platform-observation intervals ranged from **1.348 to 4.315 seconds**, with a **2.762-second median**.
These intervals do not measure exact click time, total decision time, or a general latency bound.
Trial counts do not establish independent samples, better picks, or season results.

After handoff, all four exact Week 1 contexts had fresh browser observations and verified selected-team locks.
The [server acceptance record](SERVER_ACCEPTANCE.md) verifies zero new lineup authorizations and zero unresolved authorized claims after handoff.
Live server lineup submission and an unattended season remain unverified.
At that checkpoint, two of three additional draft trials were complete.
The subsequent fifth trial is recorded above. The five-team season evaluation remains planned.

## Published v0.3.1 evidence

The [v0.3.1 GitHub prerelease](https://github.com/krmisystems/fantasy-football-manager/releases/tag/v0.3.1) uses commit `5fd4727d0f21751508c9caac3fba62ba03c8c756`.
All seven [main CI jobs](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34262013806) passed.
All five published asset downloads matched the reviewed hashes and sizes.

The [v0.3.1 PyPI package](https://pypi.org/project/fantasy-football-manager/0.3.1/) passed the [approved publication workflow](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34262132640).
A fresh public PyPI installation passed STDIO checks for 17 manager tools and 13 ESPN tools.
Both commands reported version 0.3.1. Capability and status calls passed.
Both public PyPI distributions matched the reviewed hashes and sizes.
The check used a fresh Python 3.12.13 environment with cache, local configuration, and environment overrides disabled.

The initial installation could not find the version in the public simple index.
The same check passed after the index listed version 0.3.1.
These checks did not open a browser or submit a live action.

The [MCP Registry v0.3.1 record](https://registry.modelcontextprotocol.io/v0.1/servers/io.github.krmisystems%2Ffantasy-football-manager/versions/0.3.1) was active and latest at 18:28:25 UTC on 2026-09-08.
Exact-version and latest responses matched the reviewed metadata.
The [GitHub OIDC workflow](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34262942173) passed from the release commit.

The local Codex plugin was installed and enabled at version 0.3.1 with a Codex cachebuster at that check.
All six installed files matched the cache. The private SSH configuration, including `PROGRAMDATA`, remained byte-identical.
The separate server upgrade verified all 22 installed v0.3.1 package files without dependency version changes.
The preserved manager SSH connection passed initialization, 17-tool listing, capability, and source-status checks.
The ESPN SSH check used the saved transport and executable with only the state directory redirected to temporary isolated state.
It passed initialization, 13-tool listing, and disconnected status checks. The temporary state was removed afterward.
This avoided lifecycle status writes to the running coordinator. The preserved ESPN league target was not launched during this check.
A new thread must load the updated local plugin.

The third draft's saved host capture matched all 133 existing server picks and completed the stored 160-pick history.
That import uses a separate reconciliation source. It does not establish a fresh server draft-room observation.
After the v0.3.1 server upgrade, all three Week 1 contexts produced fresh season observations and zero unresolved claims.
Selected-team locks were verified. No single lineup swap qualified under the configured limits.
Those third-draft checks did not establish live writes from the corrected package.
The subsequent fourth draft provides separate installed v0.3.1 execution evidence above.

## Published v0.3.0 evidence

Version 0.3.0 is published on [GitHub](https://github.com/krmisystems/fantasy-football-manager/releases/tag/v0.3.0) and [PyPI](https://pypi.org/project/fantasy-football-manager/0.3.0/).
The [MCP Registry record](https://registry.modelcontextprotocol.io/v0.1/servers/io.github.krmisystems%2Ffantasy-football-manager/versions/0.3.0) was active and latest at publication.
The package source commit is `d3acc32150ad71b0d85847f603fcd7649a2436b7`.
The separate [Registry workflow](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34199217116) published unchanged package metadata from documentation and workflow commit `dd5ce3a50dbc2145b8ead701e8b9ddb593d2a62c`.

The final Windows run passed **608 tests with two skips in 33.48 seconds**, including 15 isolated Chrome cases.
The skips required PostgreSQL configuration and Windows symlink privileges.
Separate Linux runs passed 23 PostgreSQL archive tests and 28 discovery collector tests.
All seven [source CI jobs](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34197957763) passed.
The [PyPI workflow](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34198024653) passed the same seven gates before approved publication.

All five GitHub asset downloads matched their reviewed hashes and sizes.
Both PyPI distributions matched the reviewed CI artifact hashes.
Before PyPI approval, all 22 wheel package files and 92 source archive files matched the source commit.
The Windows GitHub build and Linux PyPI build have separate archive hashes. Each build was checked against the same source commit.

A fresh Python 3.12.13 environment installed version 0.3.0 from the public PyPI index with cache and local configuration disabled.
Both installed commands passed STDIO initialization and tool listing: 17 manager tools and 13 ESPN tools.
Both reported version 0.3.0. Read-only capability and status calls passed.
The local Codex plugin also passed both SSH STDIO checks against the installed server package.
These checks did not submit a live draft pick or lineup change.
Package publication and a personal plugin installation do not establish official Codex marketplace inclusion.

## Working-tree live draft: Complete with failures and manual interventions

The tested 10-team PPR snake draft used 16 rounds.
The runtime used installed v0.2.1 dependencies with changing working-tree patches, including the v0.2.2 candidate.
The selected roster is complete with 16 players.
The manager confirmed submissions at picks 30, 31, 50, 51, 70, 71, 90, 91, 110, 111, 130, 150, and 151.
ESPN Autopick made picks 10, 11, and 131.

Initial adapter failures prevented the first two manager selections.
At pick 131, manual autocomplete selection was too late. The manager reconciled its failed proposal as `not_selected`.
Later restarts exposed availability and position parser gaps. Fixes restored operation before confirmed picks 150 and 151.
The run required manual interventions and does not establish unattended operation.
No duplicate submissions were observed.

The 13 confirmed receipts had a median authorization-to-observation time of 3.71 seconds and a range of 2.21–4.84 seconds.
These measurements exclude failed proposals, platform fallback selections, and the simulation stage.
They do not establish a general latency bound.

The complete local suite passed **509 tests in 31.78 seconds** on Windows with Python 3.12.13.
The run used `FFM_BROWSER_TESTS=1` and included **15 isolated Chrome cases**: 5 draft cases and 10 season cases.
The final post-draft observation verified all 160 selections, complete history, and the 16-player roster.
A fresh Week 1 season connection and sync observed that roster and produced lineup status `ok`.
The snapshot contained 1,036 player records, including 494 weekly projections, with verified locks for the selected team only.
All 9 starter slots were filled. Current and optimized lineups both had an estimated 125.35 points, with 0.0 improvement.
No season action was submitted, and no pending claim remained.
Version 0.2.2 is published. Its package and installation evidence appears below.
This working-tree run does not establish live write acceptance for an installed v0.2.2 wheel.
Read the [live draft acceptance record](LIVE_DRAFT_ACCEPTANCE.md) for the failure log, manual interventions, receipts, and evidence boundaries.

## Published v0.2.2 evidence

The [v0.2.2 prerelease](https://github.com/krmisystems/fantasy-football-manager/releases/tag/v0.2.2) uses commit
[`b15f1a506aac83ca44365df5511fcd15b43e1d44`](https://github.com/krmisystems/fantasy-football-manager/commit/b15f1a506aac83ca44365df5511fcd15b43e1d44).
All six jobs in its [GitHub CI run](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34192876128) passed.
The jobs covered Windows and Ubuntu with Python 3.11 and 3.14, isolated Chrome cases, and packaging.
Artifact inspection verified 103 archive members and manifest entries against the release source.
All five published asset downloads matched the approved local hashes.

The installed wheel passed STDIO checks for all 17 manager tools and 13 ESPN tools.
The checks included synthetic draft, lineup, power-ranking, and waiver calculations.
The ESPN command rejected an unknown proposal and preserved its disconnected state.

The installed ESPN MCP command also passed authenticated Week 1 connection, sync, and a five-second advisory monitor check.
It reported `monitoring_lineup`, current observations, lineup status `ok`, and no pending actions.
The current lineup matched the calculated lineup. No live action was needed or submitted.
The monitor stopped and disconnected cleanly. The saved configuration is paused.

The local Codex plugin was installed and enabled at version 0.2.2.
Both local command registrations use the selected league's separate database and the existing shared browser profile root.
The earlier league database remains separate.

Windows initially blocked the wheel replacement because older manager command processes held the tool directory open.
The operator stopped those identified manager processes and repeated installation successfully.
That installation recovery did not terminate the user's Chrome browser.

Installed-wheel draft writes and live lineup writes remain **Not Tested**.
PyPI and MCP Registry publication were incomplete at that release check.
Published assets remain fixed to the release commit. Later documentation commits do not replace them.

## Version 0.2.1 patch status

The complete local patch run passed **400 tests in 20.91 seconds** on Windows with Python 3.12.13.
The run used `FFM_BROWSER_TESTS=1` and included **14 isolated Chrome cases**: 4 draft cases and 10 season cases.
The patch addresses weekly header roles, request-bound player responses, selected-team lock coverage, ownership cache invalidation, and delayed navigation.

An authenticated read was verified through the development ESPN service and Chrome with the saved local profile:

| Check | Verified result |
|---|---|
| League and roster read | 14 teams and 14 players on the selected roster. |
| Player inputs | 1,036 players, including 494 with weekly projections. |
| Lock evidence | `locks_verified=true` with `locks_scope="selected_team"`. |
| Weekly lineup calculation | Status `ok` with 9 lineup slots. Estimated improvement was about 0.75 projected points. |
| League-wide power rankings | Incomplete because selected-team locks do not establish league-wide lock coverage. |
| Advisory monitor | Verified over 5 seconds with 3 polls. Browser ready; latest lineup status `ok`; snapshot age 1.28 seconds; no pending actions. Stopped cleanly. |
| Live draft or lineup submission | **Not Tested.** No real action was submitted. |

This evidence verifies authenticated observation and calculation. It does not verify acceptance of a live action.

## Published v0.2.1 evidence

The [v0.2.1 prerelease](https://github.com/krmisystems/fantasy-football-manager/releases/tag/v0.2.1) uses commit
[`ea72798c3bb6b08bb1bcd37e82ce1cfe5fb08d36`](https://github.com/krmisystems/fantasy-football-manager/commit/ea72798c3bb6b08bb1bcd37e82ce1cfe5fb08d36).
All six jobs in its [GitHub CI run](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34186633175) passed.
All five uploaded asset downloads matched the local artifact hashes.
The installed v0.2.1 wheel passed STDIO checks for 17 manager tools and 13 ESPN tools.
The installed ESPN MCP command also completed an authenticated connection and sync in advisory mode.
The browser reported ready. No action was submitted, and no pending action remained.
The local plugin was installed and enabled at version 0.2.1.
PyPI and MCP Registry publication were incomplete at that release check. Live write acceptance remained **Not Tested**.
Published assets remain fixed to the release commit. The v0.2.0 evidence below is historical.

## Verified v0.2.0 baseline

Version 0.2.0 adds the ESPN companion, durable browser claims, weekly lineup swaps, and a standalone worker.
The complete local run passed **364 tests in 19.41 seconds** on Windows with Python 3.12.13.
The run used `FFM_BROWSER_TESTS=1` and included **13 isolated Chrome tests**: 4 draft cases and 9 season cases.

| Area | Evidence state |
|---|---|
| Live draft and lineup policy | Verified with fictional observations: source identity, context, clock, Autopick, locks, freshness, review, and automatic modes. |
| Browser claim lifecycle | Verified with SQLite tests: exact baselines, concurrent authorization, idempotence, rollback, and reconciliation. |
| ESPN service | Verified with browser stubs: submission, uncertain results, cache invalidation, pauses, and terminal behavior. |
| Browser adapters in Chrome | Verified in 13 isolated browser cases using local page fixtures. No real league submissions. |
| Draft and season calculations | Verified through synthetic regression tests in the complete local run. |
| Packaged live draft and lineup acceptance | **Not Tested.** Requires a signed-in account and appropriate live league state. |
| Earlier direct browser draft actions | Verified in the original live session. This separate evidence does not validate the packaged adapter. |
| Live waivers, acquisitions, drops, and trades | Planned. Adapters are not implemented. |
| Automatic scoring-week rollover | Planned. Season operation uses an explicit connected week. |
| Version 0.2.0 public assets | Verified published GitHub prerelease. All five uploaded asset downloads matched the local artifact hashes. |
| Installed commands and plugin | Verified wheel STDIO checks: 17 manager tools and 13 ESPN tools. Local plugin version 0.2.0 installed and enabled. |
| PyPI and MCP Registry publication | Version 0.2.0 was not published on these channels. Publisher setup was incomplete at that check. |

Automated tests do not submit picks or lineup changes to a real league.
Local fixture tests do not establish compatibility with current ESPN pages or live account acceptance.
Source checks do not establish publisher ownership or a public marketplace listing.

## Published v0.2.0 evidence

The [v0.2.0 prerelease](https://github.com/krmisystems/fantasy-football-manager/releases/tag/v0.2.0) uses commit
[`f9825892f4af64d7abc501e5ef15b46ef5501411`](https://github.com/krmisystems/fantasy-football-manager/commit/f9825892f4af64d7abc501e5ef15b46ef5501411).
All six jobs in its [GitHub CI run](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34185668423) passed.
The run covered Windows and Ubuntu tests, isolated Chrome fixtures, and packaging.
The five uploaded assets passed download and hash comparisons after publication.
The installed wheel passed both STDIO checks. The local plugin was installed and enabled at version 0.2.0.
These installation checks did not authenticate ESPN or submit a real action.
Published assets remain fixed to the release commit. Later documentation commits do not replace them.

## Release checks

```sh
uv run pytest -q
uv run fantasy-football-manager --demo
uv run python scripts/validate_release.py --version 0.3.2
uv build
uv run python -m twine check "dist/*.whl" "dist/*.tar.gz"
uv run python scripts/build_plugin_zip.py
```

The browser cases are opt-in. With installed Chrome, run them in PowerShell:

```powershell
$env:FFM_BROWSER_TESTS = "1"
uv run pytest -q tests/test_browser_integration.py tests/test_season_browser_integration.py tests/test_espn_public_draft_integration.py
Remove-Item Env:FFM_BROWSER_TESTS
```

These tests use isolated browser contexts and local fixtures.
Validate the installed manager command and companion command separately.
Validate the plugin manifest and all three skills before installation.
Do not describe a read-only connection check as a completed live submission test.

## Historical baseline

The 0.1.0 source passed 105 local tests and installed manager command checks.
Its [initial GitHub source run](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34182051866) covered Windows and Ubuntu.
Those historical results apply to the tested 0.1.0 commit, not automatically to 0.2.0.
