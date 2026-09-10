# Server and archive acceptance

**Historical status: Verified v0.3.2 five-team Week 1 observation and analysis, archive import, backup recovery, and service restart.**

This record includes the v0.3.2 five-team handoff and retains the earlier versioned checks on 2026-09-08.
Read [HTTP season acceptance](HTTP_SEASON_ACCEPTANCE.md) for the deployed v0.4.0 candidate and its five-team HTTP observation sweep.
One explicitly authorized Week 1 repair also verified automatic HTTP free-agent add/drop and a subsequent lineup exchange through that candidate.
Both actions had ESPN `EXECUTED` receipts and matching roster observations.
The execution harness applied temporary explicit limits and restored the original policy afterward.
Live waiver processing, IR moves, scoring-week rollover, and public release remain incomplete.
Production archive compaction, incremental bootstrap, exact event coverage, and scheduled collection passed.
Deployment identities, account information, manifests, and raw evidence remain private.
The checks below describe the tested configuration. They do not establish unattended season operation.

## Five-team season handoff

The [fifth draft](FIFTH_DRAFT_ACCEPTANCE.md) required operator recovery after an opponent selection with no season projection blocked history.
Its final host capture verified all 160 league picks and matched the stored 132-pick prefix.
The result retains 13 manager confirmations, two direct host-browser confirmations, and one unattributed selection.
The v0.3.2 recovery import used a separate source provider and the original host observation time.
It preserved all 501 earlier player records and their projection timestamp. Only the missing opponent identity was added, with unknown projected points.

The recovery and activation helpers passed 57 isolated checks and independent review.
Their transaction guards reject changed history, configuration revisions, and unresolved authorized claims.
The original gate that required 16 manager confirmations remained blocked and unchanged.

Before the upgrade, the archive recorded five separate event cutoffs and preserved every existing immutable run.
Five new collection runs use `null` runtime and code revision fields because their exports include earlier history.
The prior draft remains attributed to unchanged installed v0.3.1 methods and a private orchestration launcher.
The later history recovery and season observations use v0.3.2.

All 22 installed files matched the reviewed v0.3.2 wheel after the upgrade. Dependency versions remained unchanged.
The coordinator started at **21:12:39 UTC** with five explicit 2026 Week 1 team contexts.
Activation preserved the four existing contexts and policies.

At **21:15:18 UTC**, two complete coordinator cycles had passed.
All five teams had complete, fresh `espn_browser` observations, verified selected-team locks, and current accepted lineup calculations with status `ok`.
The calculations matched the saved state and configuration revisions and their input fingerprints.
Source ages ranged from 62 to 75 seconds, rounded, within the configured 300-second limit.
All five lineup modes were automatic and unpaused, with a 1.5-point minimum improvement.
There were zero unresolved claims and zero new lineup authorizations.

An independent check after three completed cycles confirmed the same conditions.
No post-start error or attention transition appeared in the checked durable events.
A privileged journal read also found no error entries during the checked window.
The review account could not read the journal directly; the privileged read resolved that evidence gap without a permission change.

These checks verify five-team observation and analysis. No live server lineup swap occurred during the checked cycles.
Live server lineup submission and an unattended season were **Not Tested** at that v0.3.2 checkpoint.
At this v0.3.2 handoff, automatic week rollover, live waivers, drops, acquisitions, and trades were not implemented.
Read [the multi-team evaluation plan](MULTI_TEAM_ACCEPTANCE.md) for the remaining season evidence.

## Five-team archive and backup verification

At **21:22:15 UTC**, every outbox event through each checked cutoff was present in the archive:

| Anonymous source | Checked events | Missing events |
|---|---:|---:|
| Team A | 3,126 | 0 |
| Team B | 3,129 | 0 |
| Team C | 1,101 | 0 |
| Team D | 1,432 | 0 |
| Team E | 1,378 | 0 |

All earlier immutable run metadata remained unchanged.
The fifth draft's selections at 146 and 155 received `host_browser` executor labels from their exact host receipts.
Selection 135 received an `unknown` label. A missing manager receipt was not treated as evidence of Autopick.
The label update preserved all earlier operator labels, source contexts, and run metadata.
These counts verify storage coverage. Mixed-history collections can repeat evidence and do not represent independent outcomes.

The backup created at **21:23:32 UTC** contains eight files: one PostgreSQL dump, five SQLite databases, and two private configuration files.
All eight sizes and SHA-256 checksums matched their manifest entries.
Every SQLite backup passed `PRAGMA quick_check` and matched its expected fresh Week 1 context.
`pg_restore --list` read the PostgreSQL dump successfully. A new PostgreSQL restore was **Not Tested**.

The final check at **21:25:11 UTC** passed after ten completed coordinator cycles.
All five current lineup calculations, contexts, locks, and effective policies still passed.
Source ages ranged from 31.8 to 46.2 seconds. There were zero unresolved claims, new lineup authorizations, or manager lineup submissions.
Team B already had the target lineup. Teams A, C, D, and E had no admissible single exchange under their limits.
The archive, backup, and discovery timers were active. Their latest service results were successful with exit code zero.
The coordinator continued five-team visits after verification.

## Historical four-team season handoff and backup

The [fourth draft](FOURTH_DRAFT_ACCEPTANCE.md) confirmed all 16 own picks and captured 160 picks through the live server browser.
Its private launcher exited successfully and released the shared profile before season activation.
The activation preserved the three existing contexts and policies. It added the fourth team's explicit Week 1 context.
All 22 installed package files still matched the reviewed v0.3.1 wheel.

The check at 19:39:56 UTC passed after two complete coordinator cycles.
All four contexts used fresh `espn_browser` observations and verified selected-team locks.
Their observed source ages ranged from 51 to 61 seconds.
All four lineup modes were automatic and unpaused, with a 1.5-point minimum improvement.
The coordinator reported healthy status and zero unresolved or newly authorized lineup claims.

Team B already had the target lineup. Teams A, C, and D had no admissible single exchange.
No live server lineup swap was submitted during these checked cycles.
This verifies four-team observation and analysis. That v0.3.1 checkpoint did not verify live server lineup submission.

At the 19:38:32 UTC archive check, every outbox event through each checked cutoff was present:

| Anonymous source | Checked events | Missing events |
|---|---:|---:|
| Team A | 3,024 | 0 |
| Team B | 3,027 | 0 |
| Team C | 1,000 | 0 |
| Team D | 1,329 | 0 |

Existing immutable run metadata remained unchanged.
The fourth source began with a fresh database and retains v0.3.1 source provenance plus the private launcher's collection scope.
The earlier mixed-history collection runs retain their existing version limits.
These storage counts do not represent independent outcomes or a draft success rate.

The backup created at 19:39:10 UTC followed the four-team coordinator start.
It contains seven files: one PostgreSQL dump, four SQLite databases, and two private configuration files.
All seven sizes and SHA-256 checksums matched their manifest entries.
Each SQLite backup passed `PRAGMA quick_check` and its exact Week 1 context check.
`pg_restore --list` read the PostgreSQL dump successfully.
A new PostgreSQL restore was **Not Tested** for this backup. The historical restore check remains below.

The archive, backup, and discovery timers were active. Their latest service results were successful.
The coordinator continued four-team visits after verification.
At that checkpoint, one further draft and the five-team evaluation remained planned.
The subsequent fifth draft and five-team observations appear above.

## Historical version 0.3.1 third-team handoff

The [third draft record](THIRD_DRAFT_ACCEPTANCE.md) preserves the completed roster, failures, recovery steps, and final host-capture reconciliation.
The final snapshot contains 160 picks and zero unresolved authorized claims.
Its reconciliation provider does not establish fresh browser state or permission for a live action.

The server installed the reviewed v0.3.1 wheel after the draft evidence was saved.
All 22 installed package files matched the reviewed wheel. Dependency versions remained unchanged.
The archive, backup, and discovery timers resumed after the package update.
The third team's activation preserved the two existing league contexts and their policies.

The coordinator then observed all three exact Week 1 contexts through the authenticated browser.
All three sources used `espn_browser` and verified selected-team locks.
All three lineup modes were automatic and unpaused, with a 1.5-point minimum improvement.
The coordinator reported healthy status, fresh observations, and zero unresolved claims.

One team already had the current target lineup.
The other two teams had no admissible single exchange under the configured limits.
No live server lineup swap was submitted.
These checks verify observation and analysis. They do not establish live lineup submission or unattended season completion.

The remote manager command passed the preserved plugin's SSH initialization and listed 17 tools at version 0.3.1.
The ESPN command listed 13 tools through the same SSH transport and executable, with its state directory temporarily isolated.
That isolation prevented lifecycle status writes to a live league database. The temporary state was removed after verification.
The check did not launch the preserved ESPN league target or connect another browser.

## Historical three-team archive and backup verification

The final check at 18:38 UTC recorded six completed coordinator cycles and fresh observations for all three teams.
The archive preserved every earlier immutable run payload.
Three new collection runs contain mixed historical and post-upgrade evidence.
Their runtime version and code revision fields are `null`, because the exporter also reads earlier database events.
A private cutover record identifies the installed v0.3.1 package and the event boundaries.
The original third-draft run retains its v0.3.0 private-bootstrap provenance.

The archive imported three explicit operator-observation labels for the third draft's platform fallback selections.
It contained every outbox event through the checked cutoffs:

| Anonymous source | Checked events | Missing events |
|---|---:|---:|
| Team A | 2,958 | 0 |
| Team B | 2,960 | 0 |
| Team C | 934 | 0 |

These are storage checks. Mixed-history exports can repeat earlier evidence under a separate collection run.
The record counts do not represent independent draft or season outcomes.

The completed backup contains a PostgreSQL dump, all three SQLite databases, and two private configuration files.
All six files matched their recorded sizes and SHA-256 checksums.
Each SQLite backup passed `PRAGMA quick_check` and matched its expected Week 1 context.
`pg_restore --list` read the PostgreSQL dump successfully.
A new PostgreSQL restore was **Not Tested** for this backup. The earlier restore check remains recorded below.

The archive, backup, and discovery timers were active. Each timer's latest service result was successful.
The coordinator continued its three-team visits after verification.

## Historical v0.3.0 regression verification

The Windows run passed **579 tests**, with one optional PostgreSQL test skipped, in 35.20 seconds.
It used Python 3.12 and included all 15 isolated Chrome cases through `FFM_BROWSER_TESTS=1`.
The separate Linux run below covers the PostgreSQL integration test.
Release metadata, generic deployment files, and known private-pattern checks passed before packaging.

The local Codex plugin uses private SSH STDIO commands to the server.
Both v0.3.0 MCP handshakes passed: 17 manager tools and 13 ESPN tools.
Read-only status calls passed through those connections.
The initial Windows SSH check failed because the filtered environment omitted `PROGRAMDATA`.
The private plugin now supplies that variable. The repeated checks passed.

## Archive verification

The archive tests passed on Linux with PostgreSQL 16: **23 tests passed**.
The database test used an isolated validation schema.
It checked transactional import, repeat import, and rejection of conflicting immutable run metadata.
The test removed its temporary schema after completion.

The production archive accepted the initial sanitized backfill in one transaction.
A second import of that bundle inserted **zero runs, records, labels, or imports**.

| Initial backfill item | Count |
|---|---:|
| Run records | 2 |
| Evidence records | 2,128 |
| Evidence labels | 4,186 |
| Bundle imports | 1 |

| Evidence record kind | Count |
|---|---:|
| Snapshots | 22 |
| Observed draft picks | 160 |
| Browser proposals | 19 |
| Audit and runtime events | 1,909 |
| Classified failure records | 16 |
| Configuration records | 2 |

These are storage counts. Several records or labels can describe the same underlying event.
The counts are not independent outcome samples or a draft success rate.
Failure categories describe message patterns. They do not establish a root cause.

The schema contains `archive_imports`, `archive_runs`, `archive_records`, and `archive_labels`.
Content hashes identify sanitized records and bundle contents.
Foreign keys connect records to runs and labels to records.
The importer preserves existing evidence and rejects changes to an existing run's metadata.

## Backfill provenance

The backfill used two explicitly selected manager databases and structured historical datasets.
Both current database snapshots were already in the season phase.
The separate final draft snapshot supplied the complete history of 160 selections.

One source database contained season observations and no browser draft proposal receipts.
The other contained 19 browser draft proposals: 13 `confirmed`, one `not_selected`, and five `pending`.
It contained 14 durable authorizations and 14 reconciliation results.
Proposal baselines retained earlier draft states.

The historical live draft used changing development patches.
Its run metadata retains unknown version and commit fields as `null`.
The archive exporter version identifies the export software. It does not identify the software that executed each historical action.
See the [live draft acceptance record](LIVE_DRAFT_ACCEPTANCE.md) for that run's execution limits.

Three known fallback selections have explicit operator-observation labels for ESPN Autopick.
The exporter does not infer Autopick from a missing receipt or a `not_selected` result.
Authorization, browser return, observed selection, and executor attribution remain separate evidence.

The sanitized backfill passed checks for known private member identifiers, fantasy-team names, personal paths, member query values, and cookie keys.
The archive retains private league and team identifiers for context matching.
It is not a public dataset.

## Initial two-team season observation

The server observed both configured team contexts through its authenticated browser.
Saved lineup modes were `automatic`, with a minimum projected improvement of 1.5 points.
The checks required no lineup changes and left zero pending claims.

This verifies observation, saved-policy access, and analysis on the server.
That historical checkpoint did not verify live server lineup submission.
No server lineup submission is claimed by this check.

## Backup and restart checks

The daily backup timer is enabled with 14-day retention on a separate physical disk.
The first completed backups contained a PostgreSQL dump, two SQLite databases, and two private configuration files.
Every listed backup file matched its recorded size and SHA-256 checksum.
Both SQLite backups returned `ok` from `PRAGMA integrity_check`.

A PostgreSQL restore into a separate validation database matched all four source table counts:

| Table | Source rows | Restored rows |
|---|---:|---:|
| `archive_imports` | 5 | 5 |
| `archive_runs` | 4 | 4 |
| `archive_records` | 3,351 | 3,351 |
| `archive_labels` | 8,049 | 8,049 |

These counts include initial server collection after the historical backfill.
The archive timer paused during this comparison. The season worker continued to collect local evidence.
The archive timer resumed after verification.

The coordinator stopped during an active Chrome visit in 3.13 seconds.
Chrome exited, the profile lease released, and a new service process started successfully.
This was an observation shutdown. No live submission was in progress.
Automated tests cover cooperative shutdown with pending work and unresolved claims.

The temporary browser-view services and SSH viewing tunnel then stopped.
A subsequent server sweep completed with fresh observations for both teams.
This verifies independence from the viewing connection.
Physical shutdown of the operator computer and a full server reboot were **Not Tested**.
The coordinator, display service, archive timer, and backup timer are enabled for startup.
