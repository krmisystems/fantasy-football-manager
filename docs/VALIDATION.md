# Validation status

Version 0.3.0 adds a server coordinator and labeled evidence archive.
Read [server acceptance](SERVER_ACCEPTANCE.md) for current tests, two-team observations, backup recovery, and verification limits.
The historical results below retain their original runtime scope.

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
PyPI and MCP Registry publication remain incomplete.
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
PyPI and MCP Registry publication remain incomplete. Live write acceptance remains **Not Tested**.
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
| PyPI and MCP Registry publication | Not published. Separate publisher setup remains required. |

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
uv run python scripts/validate_release.py --version 0.2.2
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
