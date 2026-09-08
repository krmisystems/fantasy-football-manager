# Fifth draft acceptance

**Status: Verified final host history and roster completion, with a parser failure and operator recovery.**

The final browser capture contains all 160 selections from a 10-team PPR snake draft.
The selected roster contains 16 players: 13 manager-confirmed picks, two direct host-browser picks, and one unattributed selection.
This trial does not establish unattended completion or live draft acceptance for version 0.3.2.

## Runtime and selection evidence

The draft used installed v0.3.1 from commit `5fd4727d0f21751508c9caac3fba62ba03c8c756`.
All 22 installed package files and the private orchestration launcher matched their recorded hashes after the worker stopped.
Package execution methods remained unchanged during the live run.
The launcher handled collection and lifecycle. The operator did not apply a runtime compatibility patch.

The league had 16 rounds. The selected team drafted from slot 6.
The server confirmed the first 13 own selections before history normalization failed.
The separate host browser entered only after the operator stopped the server worker and verified zero unresolved authorized claims.

| Evidence source | Overall picks | Count |
|---|---|---:|
| Manager submission with a confirmed platform observation | 6, 15, 26, 35, 46, 55, 66, 75, 86, 95, 106, 115, 126 | 13 |
| Direct host-browser click with a matching roster and history observation | 146, 155 | 2 |
| Verified platform selection with an unknown executor | 135 | 1 |

The host browser first reached the draft at pick 139, after pick 135 had passed.
The roster already contained the player selected at pick 135. The host submitted no click for that turn.
No retained evidence identifies its executor. A missing manager receipt does not establish ESPN Autopick.

The host selected a D/ST at 146 and a kicker at 155.
Each selection used one visible, enabled `Draft` button after verification of the current turn and selected team.
Autopick was off before and after both clicks. Fresh roster and Activity observations confirmed each result.
The host used the highest available projected player at the required position from the visible table.
The preferred kicker had already been selected before the final turn, so the host selected the next available candidate.

## Failure and recovery

An opponent selected a player at pick 133 whose verified ESPN identity had empty full-season projection statistics.
Version 0.3.1 excluded that player from its projected pool before matching visible history.
The parser then could not resolve the selected player. The stored history remained at 132 picks with current pick 133.
This was an identity-retention failure caused by missing projection data. The visible injury label was not the cause.

The operator stopped the worker with no unresolved authorized claim.
The process exited successfully and released the profile lease.
The host browser completed the remaining two own turns and stayed open through the final league selection.
The fallback did not recover pick 135 before its turn expired.

## Final history comparison

The final accessibility capture started at **20:47:08.832 UTC on 2026-09-08** and completed about 1.9 seconds later.
The browser displayed global draft completion, the complete 16-player roster, and disabled Autopick.
The saved text retained every row after removal of accessibility node numbers and indentation.
Its length and checksum matched the captured row text.

Private checks matched all 160 rows to player names, NFL teams, positions, and expected snake-order owners.
All 132 previously stored picks matched the captured prefix exactly.
The comparison retained the existing 501 player records and added the missing verified opponent identity with `projection=None`.
Unknown projected points remained unknown. The comparison did not invent a zero-point forecast.

The reviewed v0.3.2 runtime imported this history with provider `espn_host_browser_reconciliation`.
The import preserved the draft configuration, 501 prior player records, projection timestamp, and selection attribution.
A transaction guard rejected changed revisions, changed history, and unresolved claims before any import mutation.
The private recovery and activation helpers passed 57 isolated checks and independent review.
Fresh Week 1 observations are recorded separately in [server acceptance](SERVER_ACCEPTANCE.md).
That handoff verified all five teams, current lineup calculations, archive cutoff coverage, and an eight-file backup.
A complete host capture does not establish current server browser state or permission to submit a season action.

## Measured work

The frozen durable event record contains **1,124 completed, accepted calls and 44,960 completed trials**.
All calls have disposition `current`. No completed call was discarded, and no record was excluded from the count.
These totals describe manager calculations before host reconciliation. They do not count host actions or establish selection causality.

All 13 manager receipts contain authorization and platform observation timestamps.
Their median interval was **2.449 seconds**, with a **1.323 to 3.500 second range**, rounded from the retained timestamps.
This measures authorization to platform observation. It does not measure exact click time, network latency, or the full decision cycle.
The two host receipts record separate observation and click-return times. They are excluded from the manager timing summary.

The primary read-only supervisor collected 1,051 samples without a read error.
Before the parser failure, 872 samples showed source ages no greater than 8 seconds and no enabled Autopick flag.
An optional error-capture helper exited with SSH code 1 and no retained error output. Its cause remains unknown.
That helper restarted with error capture. The primary supervisor remained active, and the draft worker was not restarted.

The simulation uses conditional player availability and projected value over a two-pick horizon.
More trials do not establish independent outcome samples, better selections, or championship odds.

## Version 0.3.2 regression evidence

Version 0.3.2 retains a verified opponent identity when its season projection is absent or empty.
The player counts toward the opponent's roster size and position limits.
The engine excludes that player from projected values, replacement values, and recommendation pools.
Available players and selected-team players still require full-season projections.
Ambiguous names, incorrect owners, and incomplete history still block normalization.

The [parser tests](../tests/test_espn_data.py) cover API, Activity, plain history, accessibility history, and a complete 160-pick replay.
The [engine tests](../tests/test_draft.py) check roster occupancy, excluded scoring inputs, and missing weekly evidence.
The base local run passed 611 tests with 19 skips. The separate Chrome run passed all 17 integration cases.
Combined, these runs passed **628 tests**, with two remaining skips for PostgreSQL configuration and Windows symlink privileges.
All seven [source CI jobs](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34278096118) passed for commit `2810a7503073a52b4f80aacc4a35bf8d987530c5`.
The jobs covered Windows and Ubuntu on Python 3.11 and 3.14, Chrome integration, PostgreSQL integration, and packaging.
Read [distribution acceptance](DISCOVERY_ACCEPTANCE.md) for publication records.
No live draft used version 0.3.2. Its fixture results do not relabel this v0.3.1 run as corrected-wheel acceptance.

The [compatibility matrix](ESPN_COMPATIBILITY.md) records the fix and its limits.
The [fourth draft](FOURTH_DRAFT_ACCEPTANCE.md) remains a separate successful installed-v0.3.1 trial.
All three additional drafts are complete, with different failure and execution records.
The five-team season evaluation remains [Planned](MULTI_TEAM_ACCEPTANCE.md).
Private identifiers, deployment details, raw captures, and receipts remain outside the public repository.
