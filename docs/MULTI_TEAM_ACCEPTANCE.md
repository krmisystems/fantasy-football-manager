# Multi-team acceptance plan

**Status: One additional draft completed with failures and operator recovery. Two drafts remain planned.**
The [third team draft](THIRD_DRAFT_ACCEPTANCE.md) is the first of the three additional trials.
It verified all 160 selections and a 16-player roster, with 13 manager-confirmed picks and three platform fallbacks.
The five-team season evaluation remains planned. Season outcomes are not yet recorded.

Version 0.3.0 adds a serial season coordinator with separate league databases and a shared server browser.
Three-team Week 1 server observation is recorded in [server acceptance](SERVER_ACCEPTANCE.md).
Five-team season acceptance remains planned.

## Failures to retain

The second live draft exposed these failures:

- Adapter startup failed before the first two selected-team turns. ESPN Autopick made those selections.
- A later player search required an autocomplete selection. The adapter timed out, and ESPN Autopick made that selection.
- A restart required complete history recovery. A `WR, CB` position label exposed another history parsing gap.

The completed trial verified all 160 league picks and a 16-player roster.
The manager confirmed 13 selections. ESPN Autopick made three selections during the failures.
The Week 1 connection and advisory lineup analysis also passed. No season action was submitted.
Keep these events in the acceptance record after fixes pass.
A later successful selection does not remove an earlier missed turn or manual intervention.
See the [live draft acceptance record](LIVE_DRAFT_ACCEPTANCE.md) for the final result and runtime details.

The third team draft exposed two further compatibility failures: API team-name whitespace and a D/ST selector delimiter.
The private runtime workaround, planned restart, late browser handoff, and three platform fallbacks remain recorded in the [third draft report](THIRD_DRAFT_ACCEPTANCE.md).
Version 0.3.1 fixes both compatibility cases in isolated tests. The corrected source still needs a live draft trial.

## Separate state and browser access

Give each league its own `FFM_DATA_DIR` or `--data-dir`.
Each directory stores that league's configuration, snapshots, proposals, and audit history.
The manager and ESPN processes for one league must use the same state directory.

Use `FFM_BROWSER_DATA_DIR` when controllers must share one authenticated browser profile.
The profile lease permits only one active controller at a time.
The current source can retain separate league state while controllers use that profile in sequence.
Live acceptance of five-team scheduling and profile transitions remains pending.

The diagram shows the planned five-team evaluation using the implemented season coordinator.
Use the [server instructions](SERVER.md) to configure explicit team and week contexts.

```mermaid
flowchart LR
    A[League A state directory] --> Q[Serial season coordinator]
    B[League B state directory] --> Q
    C[League C state directory] --> Q
    D[League D state directory] --> Q
    E[League E state directory] --> Q
    Q --> S[Select one league and team context]
    S --> X[One active ESPN controller]
    X --> L[Shared profile lease]
    L --> P[FFM_BROWSER_DATA_DIR]
    P --> V[Verify page context and current state]
    V --> R[Reconcile the observed result]
    R --> W[Update only the selected state directory]
    W --> Q
```

Do not schedule overlapping drafts on one shared profile.
Overlapping drafts require separate browser directories, authenticated sessions, and controller processes.
Do not copy profile cookies to create those sessions.
Do not treat one shared profile lease as concurrent draft support.

## Three additional drafts

Use one recorded source commit and dependency environment for each run.
Record any change during a run as an intervention and identify the new commit or patch state.
Keep deliberate fault injection in isolated browser tests.

| Run | Planned focus | Result |
|---|---|---|
| Draft A | Verify waiting-room entry, identity, disabled Autopick, and readiness before the first turn. | Completed as the third team draft. Failures required operator recovery. Thirteen picks have manager confirmations, and three have operator fallback labels. |
| Draft B | Repeat automatic selection with autocomplete, complete history, and platform receipts. | Pending. |
| Draft C | Repeat through roster completion and verify the resulting league context for season monitoring. | Pending. |

For each run:

1. Record the rules, draft order, roster size, source commit, and configured limits.
2. Verify the selected team and complete history before enabling automatic submissions.
3. Record every selected-team turn, including platform fallback and manual selections.
4. Reconcile each submitted action against the platform before another submission.
5. Verify the final roster and complete draft history.
6. Record failures, interventions, and unresolved results before assigning an outcome.

A complete automatic run requires confirmed manager submissions for every required selected-team turn.
Platform fallback, manual selections, missing receipts, and duplicate attempts must remain visible in that result.
A roster that becomes full through fallback selections does not establish complete manager automation.

## Five-team season evaluation

Give the teams anonymous labels A through E in public reports.
Record the scoring rules, lineup slots, and configured policy separately for each team.
Use an explicit scoring week when connecting a season controller.
Automatic week rollover is not implemented.

For each selected team and week:

1. Load the correct state directory and verify the browser context.
2. Read current ownership, weekly projections, and selected-team locks.
3. Calculate the legal lineup under that team's configured limits.
4. Submit supported lineup changes only within the authorized mode.
5. Verify each resulting lineup before another change.
6. Record source age, lock coverage, interventions, and unresolved results.
7. Release the browser controller before another team uses the shared profile.

The current lineup adapter applies one qualifying swap at a time.
Each intermediate swap must meet the configured improvement limit.
Some optimized targets require intermediate moves that fail that limit.
Report those cases without claiming that the whole target lineup was applied.

Live waiver, free-agent acquisition, drop, and trade adapters are not implemented.
Keep their recommendations and any external manual actions separate from manager execution results.
Five-team monitoring and lineup changes alone do not establish fully automatic season management.
Selected-team lock evidence does not establish league-wide power-ranking coverage.

## Evidence to collect

| Measure | Required record |
|---|---|
| Draft completion | Required own selections, final roster size, complete history, and unresolved claims. |
| Selection source | Separate counts for manager-confirmed, ESPN Autopick, manual, and unknown selections. |
| Duplicate actions | Repeated click attempts or platform changes for the same intended action. Target: zero. |
| Source freshness | Observation age at calculation and submission, configured age limit, and stale-state blocks. |
| Receipt timing | Authorization-to-confirmation samples, sample count, and longest observed interval. |
| Manual intervention | Reason, time, affected turn or week, recovery steps, and result. |
| Correct league writes | Expected and observed context match for every action. Target: zero actions in the wrong context. |
| Week and locks | Requested week, observed week, lock coverage, and preservation of locked assignments. |
| Profile coordination | Lease contention, context transitions, unresolved claims, and controller shutdown results. |
| Simulation work | Actual completed trials, input revisions, reset events, and suppressed stale recommendations. |

These are acceptance measures, not reported outcomes.
Publish per-run and per-team results before combining them into an aggregate.
Report model scores and projected improvements as estimates.
Draft or matchup results do not establish that the model caused a win or a loss.

## Release and privacy boundary

Keep receipts, account identifiers, and raw captures outside the public repository.
Publish anonymous totals, timing samples, failure categories, and the tested source commit.
Do not publish league, team, member, player, or proposal identifiers from the live tests.

Run the full regression suite, including every isolated Chrome case, before the next release.
Keep the published version's evidence separate from working-tree experiments.
Record the completed drafts and season observations before making a multi-team acceptance claim.
