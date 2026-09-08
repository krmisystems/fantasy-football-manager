# Live draft acceptance

**Status: Verified draft completion with failures and manual interventions.** The roster contains 16 players.
The manager has 13 confirmed submissions. ESPN Autopick made three selections.
The final observation verifies all 160 selections and complete history.
A fresh season connection verified Week 1 roster observation and lineup analysis.

## Runtime and scope

The league uses a 10-team PPR snake draft with 16 rounds.
The runtime used the installed v0.2.1 dependency environment with changing working-tree patches, including the v0.2.2 candidate.
The operator restarted the runtime between turns to load compatibility changes.
This evidence applies to that development run. It does not establish live submission acceptance for an installed v0.2.2 wheel.
The user authorized automatic draft selections within the configured rules and limits.

## Failures and manual interventions

The adapter did not become ready before the selected team's first two turns.
ESPN Autopick made selections 10 and 11 during those startup compatibility failures.
Those selections are platform fallback results. They are not confirmed submissions by the manager.
The run therefore does not establish an unattended draft from its first selection.

The live room required compatibility changes in these areas:

- Use the authenticated waiting-room entry to verify draft team and member context.
- Check roster identity when the room does not expose the expected team navigation.
- Read the custom Autopick control and require it to be disabled before submission.
- Find the player search through its `PlayerName` control.
- Accept the `DRAFT_LOBBY` league subtype after the other draft checks pass.
- Load complete history before following updates from the accessible Activity view.
- Parse the accessible Activity prefixes while preserving complete, consistent pick history.

These changes preserve source identity, roster rules, and one-click authorization checks.
They do not turn missing observations into successful submissions.

At pick 131, a player-search autocomplete control prevented the expected submission flow.
The operator selected the suggestion manually, but the turn expired before a confirmed manager selection.
ESPN Autopick made the selection. The manager reconciled its proposal as `not_selected`.
That result is a failed manager proposal, not a confirmed submission.

A subsequent restart between turns exposed strict parser gaps for `DTD` and `WR CB` / `WRCB` values.
The operator applied the parser fixes and reloaded the normalizer in the running process before picks 150 and 151.
The manager then confirmed both selections.
The operator also controlled Autopick during recovery and checked browser state.

| Stage | Observed failure | Intervention and result |
|---|---|---|
| Initial turns, picks 10 and 11 | The browser adapter was not ready. | Compatibility fixes and restarts restored observation. ESPN Autopick made both selections. |
| Pick 131 | The search autocomplete blocked the expected submission flow. | Manual suggestion selection was too late. ESPN Autopick selected a player, and reconciliation returned `not_selected`. |
| Restart before the final two turns | Strict parsing rejected observed availability and position values. | Parser fixes and a normalizer reload restored operation. Picks 150 and 151 have confirmed manager receipts. |

## Confirmed submissions

The private audit contains 14 durable authorizations and 14 reconciliation results.
Thirteen results have status `confirmed`. One result has status `not_selected`.
No duplicate submissions were observed during this run.

| Overall pick | Execution source | Authorization to confirmed observation |
|---|---|---|
| 10 | ESPN Autopick during adapter startup failure | Not a manager receipt. |
| 11 | ESPN Autopick during adapter startup failure | Not a manager receipt. |
| 30 | Automatic manager submission with confirmed platform receipt | 2.24 seconds. |
| 31 | Automatic manager submission with confirmed platform receipt | 2.21 seconds. |
| 50 | Automatic manager submission with confirmed platform receipt | 3.09 seconds. |
| 51 | Automatic manager submission with confirmed platform receipt | 2.97 seconds. |
| 70 | Automatic manager submission with confirmed platform receipt | 4.55 seconds. |
| 71 | Automatic manager submission with confirmed platform receipt | 4.48 seconds. |
| 90 | Automatic manager submission with confirmed platform receipt | 3.29 seconds. |
| 91 | Automatic manager submission with confirmed platform receipt | 3.41 seconds. |
| 110 | Automatic manager submission with confirmed platform receipt | 3.94 seconds. |
| 111 | Automatic manager submission with confirmed platform receipt | 3.71 seconds. |
| 130 | Automatic manager submission with confirmed platform receipt | 4.84 seconds. |
| 131 | ESPN Autopick after the manager proposal failed | Manager result: `not_selected`. Excluded from latency measurements. |
| 150 | Automatic manager submission with confirmed platform receipt | 4.05 seconds. |
| 151 | Automatic manager submission with confirmed platform receipt | 3.87 seconds. |

The measured times run from durable authorization to the confirmed observation recorded in the private audit.
They include browser submission and reconciliation. They do not measure the full simulation and selection cycle.
Across 13 confirmed samples, the median was 3.71 seconds and the mean was 3.59 seconds.
The observed range was 2.21–4.84 seconds.
These samples exclude the failed proposal and platform fallback selections.
They do not establish a general latency bound or draft success rate.

## Regression verification

The complete local suite passed **509 tests in 31.78 seconds** on Windows with Python 3.12.13.
The run used `FFM_BROWSER_TESTS=1` and included **15 isolated Chrome cases**: 5 draft cases and 10 season cases.
Those Chrome cases use fictional pages and do not submit actions to live leagues.
The regression result and the live audit provide separate evidence.

## Final observation and season handoff

The private post-draft check verified all 160 selections and the complete 16-player roster.
It then created a fresh ESPN season browser and service for Week 1.
The season connection and sync observed all 16 roster players.
The lineup recommendation returned status `ok`.
The check submitted no season action. No pending claim remained.

| Week 1 check | Result |
|---|---|
| Observed teams and player records | 10 teams and 1,036 player records. |
| Weekly projection coverage | 494 players had weekly projections. Another 542 had no weekly projection. |
| Player locks | Verified for the selected team only, with `locks_scope="selected_team"`. |
| Starting lineup | All 9 starter slots filled. |
| Estimated lineup points | Current and optimized lineups both scored 125.35 projected points. Estimated improvement: 0.0 points. |
| Lineup action | No swap was needed or submitted. No pending claim remained. |

Projected points are estimates, not game results.
Selected-team lock evidence does not establish lock coverage for every team.
The private report retains the source observations and calculation results outside Git.

## Evidence boundaries

| Area | Current evidence |
|---|---|
| Automatic draft submission after patching | Verified for 13 selections in this development run. |
| Draft operation from the first selection | Initial failure. The platform made the first two selections through Autopick. |
| Selected-team roster | Verified complete: 16 players from 13 manager submissions and 3 platform fallback selections. |
| Complete league history | Verified: all 160 selections and complete history. |
| Duplicate submissions | None observed. The failed proposal reconciled as `not_selected`. |
| Full regression suite for these patches | Verified: 509 passed, including 15 isolated Chrome cases. |
| Unattended operation | Not established. The run required manual interventions, source fixes, and restarts. |
| Installed v0.2.2 wheel live submission | Not Tested by this working-tree run. |
| Week 1 observation and lineup analysis | Verified through a fresh season connection and sync. The 16-player roster produced lineup status `ok`. |
| Release publication | Pending. |
| Live lineup submission | Not Tested in this run. |

Raw receipts and captures remain in private storage outside the public repository.
This report contains no league, team, member, or proposal identifiers, player names, or other team names.
This report separates platform fallback selections from manager-confirmed submissions.
