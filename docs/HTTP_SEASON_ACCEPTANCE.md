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
| Lineups and acquisitions | Fictional HTTP service tests cover automatic add/drop, subsequent starting-slot assignment, and observed confirmation. | No real ESPN transaction has been submitted for this candidate at this checkpoint. |
| Waivers | Tests cover queued claims, delayed processing, terminal failure, uncertain responses, and duplicate prevention. | A queued claim does not prove ownership. |
| IR and rollover | Tests cover injury eligibility, capacity, activation, current-period evidence, and pending-claim context protection. | Live IR moves and scoring-week rollover are Not Tested. |
| Health | Tests distinguish observation freshness, analysis readiness, action readiness, and process activity. | An active process does not imply an executable recommendation. |
| Dependency isolation | Subprocess tests block Playwright imports during HTTP construction and MCP status calls. | Optional browser draft execution retains its separate dependencies. |
| Installed package | A fresh base-only installation passed actual STDIO initialization and calls for 17 manager tools and 16 ESPN tools. Playwright was absent. | These isolated calls did not contact ESPN. |
| Server deployment | All 28 installed Python files matched the reviewed wheel. Existing dependency versions and team policies remained unchanged. | The deployed coordinator has not yet submitted a live transaction. |
| Archive | All 77 archive tests passed against isolated PostgreSQL under the application role. A full restore and compaction rehearsal passed. | Production archive migration is not complete at this checkpoint. |

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

## Package and source checks

The final local suite passed **1,034 tests with 21 skips in 32.43 seconds**.
The skips comprise 17 opt-in Chrome cases, three PostgreSQL cases, and one Windows symlink case.
The separate PostgreSQL run passed all 77 archive tests.
This validation used no computer control or browser interaction.
Historical draft browser fixtures remain part of the separate CI gate.

The final wheel and source distribution passed strict Twine checks.
Release metadata and privacy-pattern checks passed.
All 28 package Python files matched the reviewed source in the wheel, source distribution, and fresh installed environment.
Actual STDIO checks reported version 0.4.0 from both servers.

The deployed wheel has SHA-256 `5dd30e509109e3723105b3676314985fef477d081f56dfd150aae7be84917a53`.
This hash identifies the privately validated deployment candidate. It is not a public release receipt.

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

## Remaining acceptance

Live acceptance requires the exact authorized roster repair, an ESPN transaction receipt, and a matching roster observation.
A follow-up cycle must show no duplicate submission.
Production archive maintenance remains in progress after a verified backup with all archive writers stopped.
Public release and cross-platform CI acceptance remain incomplete.

One successful transaction will verify that workflow for its recorded context.
It will not verify every league format, future authentication renewal, live IR execution, or an unattended season.
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
