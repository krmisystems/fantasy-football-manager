# Server and archive acceptance

**Status: Verified archive import, two-team season observation, backup recovery, and service restart.**

This record covers the v0.3.0 development candidate on 2026-09-08.
Deployment identities, account information, manifests, and raw evidence remain private.
The checks below describe the tested configuration. They do not establish unattended season operation.

## Regression verification

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

## Server season observation

The server observed both configured team contexts through its authenticated browser.
Saved lineup modes were `automatic`, with a minimum projected improvement of 1.5 points.
The checks required no lineup changes and left zero pending claims.

This verifies observation, saved-policy access, and analysis on the server.
Live server lineup submission still requires a qualifying action and a confirmed platform result.
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
