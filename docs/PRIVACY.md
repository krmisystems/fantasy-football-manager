# Privacy notes

Both MCP servers use STDIO on the computer that runs them.
That computer can be a workstation or a separately configured server.
Their data directory defaults to a location outside the source checkout.
`FFM_DATA_DIR` and `--data-dir` can select another location.

SQLite records can contain league identifiers, rules, rosters, budgets, proposals, exact baseline snapshots, and action history.
Worker status and logs can contain operational errors and league context.
The dedicated Chrome profile can retain ESPN authentication and other browser data.
The adapter does not copy cookies or credentials from another profile.
An optional local CDP connection uses the browser session selected by the user.

Authenticated requests go to ESPN through the connected browser.
The MCP servers return requested records and calculations to their client.
That client controls further transmission or retention of tool results.
The package does not include an ESPN account, hosted data service, or credentials.

## Evidence and archive data

The SQLite outbox records selected snapshots, configuration changes, calculations, action records, browser returns, and classified worker transitions.
Snapshot evidence omits account names, fantasy-team display names, navigation URLs, and source notes.
It retains player identifiers, rules, roster state, projections, source timestamps, and verification flags.
Calculation evidence separates requested trials from completed trials and records the input revisions when available.
Failure categories omit raw browser logs and exception stacks.

Browser authorization, browser return, and platform reconciliation are separate evidence.
A recorded return does not prove a click unless the adapter supplied that field.
A confirmed selection does not establish its cause without additional evidence.
Unknown executor attribution remains unknown unless an explicit observation supports a label.

The optional PostgreSQL archive contains sanitized structured evidence.
It is **not a public dataset**.
League and team identifiers remain private context fields.
Player data, strategies, budgets, action history, and operator labels can also reveal user activity.
Restrict access to archive exports and backups.

Archive manifests select each source database and structured dataset explicitly.
Private input paths do not enter exported bundles.
Snapshot exports replace original navigation URLs with canonical league URLs that omit member query values.
The exporter removes account fields, fantasy-team names, credentials, and private paths from supported structured records.
It rejects raw page, accessibility snapshot, and profile datasets.
Public samples require a separate privacy review and anonymization.

The archive timer reads the local outbox without changing it.
An archive connection failure leaves the operational database available for later export.
Local evidence writes share the associated state transaction where possible.
Backups can contain operational snapshots and connection context that the sanitized archive omits.
Keep those backups private even when their archive component passed filtering.

## Repository and deployment files

Keep the data directory, profile, logs, and real league exports out of Git and release archives.
The repository examples and test fixtures use fictional data.
Use placeholders in configuration examples.
Do not put actual hostnames, addresses, usernames, league identifiers, member identifiers, or personal file paths in public examples.
Keep deployment manifests, service overrides, database exports, and browser profiles outside Git and release artifacts.
The release validator rejects known profile paths and private runtime file names.
Pattern checks cannot identify every personal export. Review selected artifacts before publication.

Use separate private directories for separate active league contexts when needed.
Both servers and the worker must use the same directory to share policy and pause state.
Deleting runtime data can remove saved authentication and unresolved action records.
