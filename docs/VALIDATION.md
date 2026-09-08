# Validation status

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
uv run python scripts/validate_release.py --version 0.2.1
uv build
uv run python -m twine check "dist/*.whl" "dist/*.tar.gz"
uv run python scripts/build_plugin_zip.py
```

The browser cases are opt-in. With installed Chrome, run them in PowerShell:

```powershell
$env:FFM_BROWSER_TESTS = "1"
uv run pytest -q tests/test_browser_integration.py tests/test_season_browser_integration.py
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
