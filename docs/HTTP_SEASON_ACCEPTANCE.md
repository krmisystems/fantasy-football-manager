# HTTP season acceptance

**Candidate: v0.4.0. Evidence date: 2026-09-10 UTC.**

The candidate implements season operation without Chrome, Playwright, or computer control.
The existing browser adapter remains available for drafts through the optional `browser` dependency.
This record separates source tests, authenticated reads, and live transaction acceptance.
The public v0.3.3 package does not contain these new season capabilities.

## Verified scope

| Area | Evidence | Boundary |
| --- | --- | --- |
| Authentication | Authenticated HTTP reads succeeded for five private team contexts. The session owner matched each selected team. | Credentials came from an existing authorized session. Future renewal remains necessary. |
| Post-kickoff locks | A targeted team roster request returned locked players after kickoff. Broad league roster flags were insufficient. | The HTTP adapter uses targeted flags and rejects disagreement with the complete roster. |
| Projections | An empty weekly statistics object remains an unknown projection. Unchanged players cancel from a lineup comparison. | A missing current starter can prevent ordinary optimization. |
| Coverage repair | Policy tests require a named unavailable starter, an allowed replacement, and an explicitly permitted drop. | A repair can have unknown projected improvement. It cannot claim a gain over an invented zero. |
| Lineups and acquisitions | Two automatic engine cycles completed a real free-agent add/drop and a subsequent starting-slot exchange. Both ESPN transactions reported `EXECUTED` and matched fresh roster observations. | This verifies one traditional-waiver league context. Live FAAB and delayed waiver processing remain Not Tested. |
| Waivers | Tests cover queued claims, delayed processing, terminal failure, uncertain responses, and duplicate prevention. | A queued claim does not prove ownership. |
| IR and rollover | Tests cover injury eligibility, capacity, activation, current-period evidence, and pending-claim context protection. | Live IR moves and scoring-week rollover are Not Tested. |
| Health | Tests distinguish observation freshness, analysis readiness, action readiness, and process activity. | An active process does not imply an executable recommendation. |
| Dependency isolation | Subprocess tests block Playwright imports during HTTP construction and MCP status calls. | Optional browser draft execution retains its separate dependencies. |
| Installed package | A fresh base-only installation passed actual STDIO initialization and calls for 17 manager tools and 16 ESPN tools. Playwright was absent. | These isolated calls did not contact ESPN. |
| Server deployment | All 28 installed Python files matched the reviewed wheel. The installed engine completed the two authorized transactions through HTTP. | The repair used a temporary exact policy. The previous policy was restored after verification. |
| Archive | All 92 archive tests passed against isolated PostgreSQL under the application role. Production compaction, checkpoint migration, exact event coverage, and scheduled collection passed. | Long-term unattended collection remains Not Tested. |

## Authenticated observations

Five HTTP reads verified team ownership and selected-team lock evidence.
Four teams had complete lineup analysis and no projected improvement at that observation.
The remaining team had an unavailable tight end with an unknown weekly projection.
The saved drop policy blocked the proposed acquisition for that team.
No transaction policy was expanded from that observation alone.

These reads used a staged source candidate and private credentials on the server.
They did not replace the installed production package or start a browser process.
Private receipts retain exact identities and source files. Public records omit account details and deployment addresses.

The deployed coordinator then completed a five-team sweep through HTTP.
All five observations were fresh. Four teams had current analysis and no required lineup change.
The team with missing tight-end coverage reported incomplete analysis.
Overall health correctly remained degraded despite an active process and fresh observations.
The service no longer depends on a display service.

The installed local plugin also passed actual SSH and MCP STDIO checks against the server.
Both servers reported 0.4.0 and matched the reviewed tool definitions.
HTTP connect and sync verified the selected team in isolated private state.
One preconnect lease conflict cleared on a single retry after four seconds.
No transaction request occurred, and production team settings remained unchanged.
All six installed plugin files matched the personal source.
The original SSH settings remained intact apart from the two intended HTTP environment arguments.

## Verified automatic roster repair

The user approved an exact bench-player drop, free-agent addition, and tight-end replacement.
The existing tight end had a missing weekly projection and a doubtful status.
The replacement had a verified weekly projection and clear roster locks.
The original tight end remained on the active roster after the repair.

The installed engine completed two bounded automatic season cycles on 2026-09-10 UTC:

1. At 03:10:20, the engine authorized the exact free-agent add/drop.
2. At 03:10:23, a fresh roster observation confirmed the acquisition.
3. At 03:10:26, the engine authorized the starting-slot exchange.
4. At 03:10:29, a fresh roster observation confirmed the new tight end and retained bench player.

Both ESPN transaction receipts reported `EXECUTED`.
The final observation showed one weekly acquisition and no unresolved submission.
Every other roster member, starting slot, and pending transaction remained unchanged.
The previous drop policy was restored before the coordinator resumed.

The execution harness added an exact-action check before the installed HTTP permit validator.
It restricted the drop and replacement lists, then disabled acquisitions before the second cycle.
The installed selection, policy, submission, and reconciliation methods remained unchanged.
No browser process or computer control was used.
The repair did not estimate a point gain from the missing projection.
Private receipts retain the exact context and transaction identifiers.

An independent read-only check at 03:16:59 UTC found exactly two confirmed proposals and no later HTTP action events.
Each proposal had one preparation, authorization, response, and reconciliation event.
The normalized team policy matched the original policy exactly.
After the package update, all five teams had fresh observations and current analysis.
Overall health reported healthy. No further lineup action qualified.
The coordinator process group contained one Python process.

## Package and source checks

The final local suite passed **1,048 tests with 22 skips in 34.23 seconds** after the archive continuity and relative-path fixes.
The skips comprise 17 opt-in Chrome cases, four PostgreSQL cases, and one Windows symlink case.
The separate PostgreSQL run passed all 92 archive tests.
This validation used no computer control or browser interaction.
Historical draft browser fixtures remain part of the separate CI gate.

All seven [source CI jobs](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34430605670) passed for commit `4cb41ff570a4cc2300ff6cf7a0c23a9b9838fec5`.
These jobs covered Windows and Ubuntu on Python 3.11 and 3.14, isolated Chrome fixtures, PostgreSQL, and packaging.
The Windows Python 3.14.7 job passed 1,035 tests with 20 skips in 272.52 seconds.
The same commit also passed all seven [pull request CI jobs](https://github.com/krmisystems/fantasy-football-manager/actions/runs/34430608804).

The final wheel and source distribution passed strict Twine checks.
Release metadata and privacy-pattern checks passed.
All 28 package Python files matched the reviewed source in the wheel, source distribution, and fresh installed environment.
Actual STDIO checks reported version 0.4.0 from both servers.

The initially deployed wheel has SHA-256 `5dd30e509109e3723105b3676314985fef477d081f56dfd150aae7be84917a53`.
This hash identifies the privately validated deployment candidate. It is not a public release receipt.
Its 28 Python files match the committed source after newline normalization.
Five files have line-ending differences. The remaining 23 files match the commit bytes exactly.

The archive continuity fix was installed at 03:16:17 UTC after a new backup of the current operational state.
Its wheel has SHA-256 `c97ba459a0fedfd9212496dd21ca765d868a0f603db4160bf2e842aef9eae675`.
All 28 installed Python files matched this wheel. Dependency versions, team policies, the manifest, and service settings remained unchanged.
The new wheel also passed fresh base-only installation and actual MCP STDIO checks without Playwright.
The server restarted with the verified repair and its transaction evidence intact.

Final review found a relative-path failure in legacy checkpoint import.
The regression reproduced the failure and passed after the fix resolved the database path before URI conversion.
The final wheel was installed at 03:25:31 UTC with SHA-256 `c3911e18df798d47b075c9841e7697a1535b37f77db3f37526e97705184da7a1`.
All 28 installed Python files matched the wheel. Dependencies, team policies, the manifest, and service settings remained unchanged.
The final source passed 92 isolated PostgreSQL archive tests and the complete default suite reported above.

## Archive rehearsal

The rehearsal restored a verified backup into an isolated database.
It compacted 1,423 legacy import receipts without removing archived runs, records, or labels.
Exact hashes remained unchanged for 17 runs, 91,622 records, and 178,543 labels.
A real historical bundle replay inserted no duplicate evidence.

Receipt manifest text decreased from 12,654,563,617 bytes to 2,505,565 bytes.
After imports-only `VACUUM FULL`, database size decreased from 12,127,910,935 bytes to 632,699,927 bytes.
Incremental bootstrap covered five frozen source databases in 20 batches with zero audit or outbox gaps.
A subsequent sync returned an empty batch.
Read [archive operation](ARCHIVE_INCREMENTAL.md) for backup, checkpoint, replay, and recovery requirements.

## Verified production archive recovery

Production compaction preserved exact hashes for 17 runs, 92,421 records, and 178,543 labels.
All 1,435 legacy import identities and times remained unchanged.
Database size decreased from 12,345,056,279 bytes to 646,741,015 bytes after imports-only reclamation.

The first bootstrap stopped after five committed batches because a timestamp refresh changed the old raw-snapshot hash.
The fix preserved those checkpoints and added an explicit decision-hash format.
It excludes only the two refreshed observation timestamps and rejects backward observation times.
Legacy conversion requires reconstruction of the exact previous raw hash from retained evidence and the private source.
Repeated timestamp refreshes do not export duplicate full snapshots.

The resumed bootstrap completed 15 further batches at 03:18:54 UTC.
It added 948 records and 15 compact receipts, with no new runs or labels.
All 20 bootstrap batches remain committed.
Verification covered all 56,322 committed audit and outbox events across five sources, with no missing or changed record or label hashes.
Both confirmed HTTP repair transactions are archived.
The verification checkpoint contained 93,418 records, 1,455 import receipts, five source checkpoints, and 72 proposal fingerprints.

A bounded follow-up imported 75 new records in 0.525 seconds, with no duplicate full snapshots at unchanged decision revisions.
The next service cycle imported 25 records and one 457-byte receipt, with no remaining backlog.
The unchanged archive timer resumed with a 60-second interval after each completed service run.
The final portable-path package update interrupted one archive cycle during maintenance.
The service restarted successfully after the update. No checkpoint or archived evidence was reset.

## Remaining acceptance

The exact live roster repair passed transaction and roster verification.
A follow-up coordinator cycle confirmed no duplicate submission and restored five-team analysis readiness.
Production archive maintenance, checkpoint recovery, and scheduled collection passed their validation gates.
Public release remains incomplete.

The two successful transactions verify that workflow for its recorded context.
They do not verify every league format, future authentication renewal, live IR execution, or an unattended season.
Trade execution remains outside this release scope.

## Reproduce source checks

Install the locked development and server dependencies:

```sh
uv sync --locked --dev --extra server
```

Run the complete default test suite:

```sh
uv run python -m pytest -q
```

Run the HTTP fixture checks without a browser:

```sh
uv run python -m pytest -q tests/test_espn_http_auth.py tests/test_espn_http_client.py tests/test_espn_http_data.py tests/test_espn_http_policy.py tests/test_espn_http_actions.py tests/test_espn_http_service.py tests/test_dependency_isolation.py
```

The default suite skips opt-in Chrome and PostgreSQL cases without their test settings.
HTTP fixture tests use fictional teams and do not contact ESPN.
Read [HTTP compatibility](ESPN_HTTP_COMPATIBILITY.md) for the verified request contract and primary source evidence.
