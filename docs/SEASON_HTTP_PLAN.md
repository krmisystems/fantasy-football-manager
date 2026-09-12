# Browser-free season automation

Status: Implemented and published in the v0.4.0 preview. One authorized Week 1 repair verified automatic HTTP free-agent add/drop and lineup execution.
Broader live acceptance and stable publication remain incomplete.

## Scope

The season service uses authenticated ESPN HTTP requests.
It implements lineup changes, free-agent additions, waiver claims, required drops, IR moves, and scoring-week rollover.
Existing draft support remains available. This work does not add trade execution.

The four operational repairs are:

1. Establish player lock state after kickoff from the targeted ESPN team roster response.
2. Preserve missing projections as unknown and identify missing starter coverage.
3. Report analysis readiness separately from observation freshness and process activity.
4. Export new archive evidence in bounded batches with durable import checkpoints.

## Action contract

Each live action requires a fresh authenticated observation and verified team ownership. The proposal records the exact context, roster, rules, policy revision, and intended transaction.

The service checks locks, eligibility, roster capacity, protected players, pending transactions, and configured limits before authorization. Waiver claims require verified claim rules and pending commitments. A pending claim does not establish player ownership.

The service records a durable submission claim before the HTTP request. An uncertain response blocks another submission. A later ESPN observation must establish the actual result.

Missing inputs remain unknown. The service must not replace missing projections with zero, invent a drop policy, or treat an unsupported response as success.

## Validation gates

| Area | Required evidence |
| --- | --- |
| Authentication | Private league reads succeed without a browser process or browser control. Credentials stay outside evidence and public artifacts. |
| Lock state | Tests cover explicit targeted flags, missing flags, conflicting rosters, and current-period context. A live post-kickoff observation must verify locked players. |
| Lineup changes | Policy tests and replay tests pass. A live authorized adjustment has an ESPN transaction receipt and a matching roster observation. |
| Acquisitions | Tests cover free agents, pending waivers, rejected claims, required drops, conflicts, budgets, roster limits, and duplicate prevention. |
| IR | Tests cover eligibility, capacity, activation, locked players, and a legal resulting roster. |
| Rollover | The service uses ESPN period evidence. Pending submissions retain their original period until reconciliation completes. |
| Health | Current successful analysis is distinguishable from a fresh observation and an active process. |
| Archive | Tests prove bounded growth, atomic checkpoints, retry behavior, replay handling, source reset handling, and legacy import support. |
| Deployment | The full required test suite passes. The deployed package matches the reviewed source. Live evidence identifies the deployed version. |

## Evidence boundaries

Public fixtures use fictional identities. Private account evidence stays outside the repository. Unit tests do not establish live ESPN write compatibility.

Authentication through an existing session was verified with HTTP only during investigation.
Targeted roster reads verified player locks after kickoff.
The [HTTP compatibility report](ESPN_HTTP_COMPATIBILITY.md) records transaction contracts from the ESPN football application.
Acquisition limits and permitted drop players remain subject to the user's explicit policy.

On 2026-09-10 UTC, the deployed candidate completed one explicitly authorized coverage repair without a browser.
Two unchanged automatic engine steps submitted a free-agent add/drop and a subsequent lineup exchange.
Both actions received ESPN `EXECUTED` receipts and matching roster observations.
The previous starter remained on the bench. Other roster players, starter assignments, and pending transactions stayed unchanged.
The execution harness used temporary explicit limits and restored the original policy afterward.

This result verifies that exact workflow in one Week 1 context.
Live waiver processing, IR moves, scoring-week rollover, and an unattended season remain Not Tested.
Read [HTTP season acceptance](HTTP_SEASON_ACCEPTANCE.md) for current results and unfinished validation.
