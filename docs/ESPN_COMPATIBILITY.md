# ESPN compatibility matrix

**Record version: 1. Target version: v0.3.0. Updated: 2026-09-08.**

This matrix describes the v0.3.0 implementation and recorded validation evidence.
Read [distribution acceptance](DISCOVERY_ACCEPTANCE.md) for verified publication status on each channel.
It does not guarantee compatibility with every ESPN layout or future website change.
Use [the ESPN workflow](ESPN_AUTOMATION.md) for operating instructions.

## Evidence terms

**Verified, fictional** means a test used invented league data or an isolated local browser fixture.
**Verified, live** means a recorded observation or action used an authenticated ESPN session.
**Planned** means the capability or acceptance trial is incomplete.
**Not Tested** means no matching acceptance result is recorded.

Fictional browser tests intercept page requests and supply controlled ESPN JSON responses.
They do not sign in to a real account or submit changes to a real league.
The test source contains inline fixtures where no separate HTML file is linked.

## Version and layout coverage

| Version introduced | Input or control | Regression fixture and checks | Evidence boundary |
|---|---|---|---|
| v0.2.0 | Draft page identity, visible clock, standard Autopick controls, exact player row | [Draft Chrome fixture](../tests/test_browser_integration.py), [browser unit tests](../tests/test_espn_browser.py), [live policy tests](../tests/test_live_policy.py) | Verified, fictional. Duplicate rows, wrong context, enabled Autopick, and repeated permits block submission. |
| v0.2.0 | Weekly roster move controls and one final confirmation | [Season Chrome fixture](../tests/test_season_browser_integration.py), [lineup claim tests](../tests/test_browser_lineup.py) | Verified, fictional. Exact roster reconciliation is required. Equivalent RB or WR slot order does not imply a conflict. |
| v0.2.1 | Weekly header with `columnheader` role; player response containing only `players` | [Season Chrome fixture](../tests/test_season_browser_integration.py), [season normalization](../tests/test_espn_season_data.py), [request provenance checks](../tests/test_espn_data.py) | Verified, fictional and live reads. A player-only response must bind to the verified request URL. |
| v0.2.1 | Selected-team move controls, incomplete league-wide locks, changed roster ownership, delayed navigation | [Season normalization](../tests/test_espn_season_data.py), [season Chrome tests](../tests/test_season_browser_integration.py), [browser navigation tests](../tests/test_espn_browser.py) | Verified, fictional; selected-team live lock reads are recorded. Own-team controls cannot establish lock coverage for other teams. |
| v0.2.2 | Authenticated waiting-room entry, numeric roster selector, hidden Autopick input in its visible control, `Player Name` search | [Public draft HTML](../tests/fixtures/public_draft_room.html), [public draft Chrome test](../tests/test_espn_public_draft_integration.py), [browser unit tests](../tests/test_espn_browser.py) | Verified, fictional. The entry and selected roster must prove the requested context before search or submission. |
| v0.2.2 | Stale API pick placeholders, truncated Activity, full Pick History recovery, Players-tab restoration | [Public draft Chrome test](../tests/test_espn_public_draft_integration.py), [draft normalization and replay](../tests/test_espn_data.py) | Verified, fictional and working-tree live recovery. History must remain contiguous and agree with player identity and snake-round ownership. |
| v0.2.2 | Exact autocomplete suggestion before the target draft row appears; status and secondary-position labels | [Public draft HTML](../tests/fixtures/public_draft_room.html), [autocomplete checks](../tests/test_espn_browser.py), [history parser checks](../tests/test_espn_data.py) | Verified, fictional; later live draft receipts followed the fixes. Ambiguous suggestions and mismatched owners still block. |
| v0.2.2 | Shared browser profile across separate league databases; standalone startup receipt | [Profile configuration tests](../tests/test_browser_profile_config.py), [service tests](../tests/test_espn_service.py) | Verified, fictional and installed observation checks. One controller holds the profile lease at a time. |
| v0.3.0 | Serial season visits, explicit league and week, graceful stop, health, pending claim recovery | [Coordinator tests](../tests/test_server.py), [server acceptance](SERVER_ACCEPTANCE.md) | Verified, fictional and two-team server reads. Zero live server lineup swaps were submitted. |
| v0.3.0 | Durable evidence, PostgreSQL import, consistent SQLite snapshots, private backup sets | [Archive tests](../tests/test_archive.py), [backup tests](../tests/test_server_backup.py), [server acceptance](SERVER_ACCEPTANCE.md) | Verified with local tests and recorded server import and recovery checks. The archive is not a public dataset. |

The version column identifies the implementation series. It does not relabel historical live runs as released-wheel acceptance.
The public draft trial used installed v0.2.1 dependencies and changing working-tree patches.

## Recorded live evidence and failures

| Observation or failure | Recorded result | Current interpretation |
|---|---|---|
| Authenticated weekly connection and sync | Installed v0.2.1 and v0.2.2 commands completed season reads and advisory calculations. | Verified live read workflow. No lineup write was submitted in those checks. |
| Draft startup compatibility failures | ESPN Autopick made the first two selections for the controlled roster. | Failure recorded. Waiting-room identity and control handling required fixes. |
| Autocomplete did not filter the player grid after text entry | At pick 131, manual suggestion selection was too late. ESPN Autopick selected a player. The proposal reconciled as `not_selected`. | Failure recorded. Exact autocomplete selection now has a fictional Chrome regression. |
| History recovery after restart | Availability and secondary-position labels exposed parser gaps. Manual recovery and patches restored complete history. | Recovery recorded. No claim of uninterrupted operation. |
| Completed live draft | All 160 league selections were verified. The selected roster contained 16 players: 13 manager-confirmed picks and 3 ESPN Autopicks. | Completed with failures and interventions. No duplicate submissions were observed. |
| Server season checks | Two configured team contexts produced current reads and analysis. Zero live server lineup swaps were submitted. | Observation verified. Saved automatic modes did not encounter a qualifying swap. Live server lineup submission remains Not Tested. |
| Future evaluation | Three additional draft trials and a five-team season trial. | Planned. No future completion, performance, or growth result is claimed. |

Read the [live draft acceptance record](LIVE_DRAFT_ACCEPTANCE.md) for failures, interventions, and receipt timing.
Read [server acceptance](SERVER_ACCEPTANCE.md) for deployment, archive, backup, and restart evidence.
The [multi-team plan](MULTI_TEAM_ACCEPTANCE.md) defines future evaluation measures.

## Repeat the checks

Install development and server dependencies from the locked checkout:

```sh
uv sync --locked --dev --extra server
```

Run unit, policy, parser, service, and coordinator checks:

```sh
uv run pytest -q
```

That command skips Chrome and PostgreSQL integration cases unless their settings are supplied.
The recorded Windows candidate run passed **579 tests**, including **15 isolated Chrome cases**, with one optional PostgreSQL case skipped.
The separate Linux PostgreSQL run passed **23 archive tests**.
These counts describe the recorded runs. Re-run the gates for a changed candidate.

Run all three Chrome fixture files with installed Google Chrome.
On Linux or macOS:

```sh
FFM_BROWSER_TESTS=1 uv run pytest -q tests/test_browser_integration.py tests/test_season_browser_integration.py tests/test_espn_public_draft_integration.py
```

On PowerShell:

```powershell
$env:FFM_BROWSER_TESTS = "1"
uv run pytest -q tests/test_browser_integration.py tests/test_season_browser_integration.py tests/test_espn_public_draft_integration.py
```

The 15 recorded Chrome cases comprise 5 draft cases and 10 season cases.
They validate browser mechanics against fictional fixtures, not the current ESPN service.

Set `FFM_ARCHIVE_TEST_DSN` to a private PostgreSQL test database before the archive integration run:

```sh
uv run pytest -q tests/test_archive.py
```

The PostgreSQL case creates and removes an isolated validation schema.
Do not put connection credentials in documentation, fixtures, or public logs.
The [CI workflow](../.github/workflows/ci.yml) supplies a disposable PostgreSQL service.
The [release workflow](../.github/workflows/release.yml) requires the same commit's matrix, Chrome, and PostgreSQL gates before packaging.

## Limits and maintenance

The supported live actions are draft picks and one legal lineup swap per proposal.
Live waivers, free-agent additions, drops, trades, and automatic week rollover remain planned.
Each intermediate lineup swap must meet the configured improvement limit.
The draft model uses a two-pick horizon and conditional availability estimates.

When ESPN changes a supported layout, record the blocked observation or action before changing the adapter.
Create a fictional fixture that reproduces the failure without private account data.
Add both a successful case and a case that must block an unsafe action.
Run the relevant fixture command and the complete release gates.
Update this matrix with the candidate version, test source, result, and live evidence boundary.
Retain previous failure records. Do not replace them with the later successful test result.
