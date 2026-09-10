# Privacy notes

Both MCP servers use STDIO on the computer that runs them.
That computer can be a workstation or a separately configured server.
Their data directory defaults to a location outside the source checkout.
`FFM_DATA_DIR` and `--data-dir` can select another location.

SQLite records can contain league identifiers, rules, rosters, budgets, proposals, exact baseline snapshots, and action history.
Worker status and logs can contain operational errors and league context.
The unreleased v0.4.0 candidate adds direct HTTP season operation with a protected session file.
Published v0.3.3 behavior uses the browser adapter. Check [validation status](VALIDATION.md) for the release boundary.

## Authentication and requests

HTTP season operation requires only the ESPN `SWID` and `espn_s2` values in a local session file.
The client reads this file when it makes a request. Credential values are not MCP tool arguments.
The file can grant account access. Keep it private and separate from league exports.
Linux checks require ownership by the running account and no group or other access.
The importer writes mode `0600`. The application does not claim equivalent automatic ACL enforcement on Windows.

The optional Linux importer reads an existing authorized Chromium database without starting Chromium.
It selects only the two ESPN session cookies and validates the supported `v10` format.
It does not import the password store, other site cookies, or a full profile.
Unsupported encryption and expired cookies stop the import. The importer does not renew the account session.
Its result reports names and status, without credential values.

The HTTP client restricts requests to the ESPN football read and write hosts documented in the [source contract](ESPN_HTTP_COMPATIBILITY.md).
It does not follow redirects or inherit system proxy settings.
Transport errors omit response bodies and credential values.
The transaction body contains the account member identifier required by ESPN. Retained receipts exclude that identifier.

The browser adapter remains available for drafts and legacy lineup operation.
Its dedicated Chrome profile can retain ESPN authentication and other browser data.
That adapter does not import credentials from another profile.
An optional local CDP connection uses the selected browser session.

Authenticated requests go to ESPN through the selected HTTP or browser adapter.
The MCP servers return requested records and calculations to their client.
That client controls further transmission or retention of tool results.
The package does not include an ESPN account, hosted data service, or credentials.

## Evidence and archive data

The SQLite outbox records selected snapshots, configuration changes, calculations, action records, transport returns, and classified worker transitions.
Snapshot evidence omits account names, fantasy-team display names, navigation URLs, and source notes.
It retains player identifiers, rules, roster state, projections, source timestamps, and verification flags.
Calculation evidence separates requested trials from completed trials and records the input revisions when available.
Failure categories omit raw browser logs and exception stacks.

Authorization, transport return, and platform reconciliation are separate evidence.
A recorded return does not prove a click unless the adapter supplied that field.
A confirmed selection does not establish its cause without additional evidence.
Unknown executor attribution remains unknown unless an explicit observation supports a label.
HTTP proposals retain exact baselines, sanitized transaction receipts, and reconciliation results in the operational database.
A pending waiver receipt does not establish player ownership.
The HTTP data tests use fictional members, teams, players, and sessions.

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

Keep the data directory, session file, profile, logs, and real league exports out of Git and release archives.
The repository examples and test fixtures use fictional data.
Use placeholders in configuration examples.
Do not put actual hostnames, addresses, usernames, league identifiers, member identifiers, or personal file paths in public examples.
Keep deployment manifests, service overrides, database exports, session files, and browser profiles outside Git and release artifacts.
The release validator rejects known profile paths and private runtime file names.
Pattern checks cannot identify every personal export. Review selected artifacts before publication.

Use separate private directories for separate active league contexts when needed.
Both servers and the worker must use the same directory to share policy and pause state.
Deleting runtime data can remove saved authentication and unresolved action records.
HTTP team lease files also remain private because their names contain league and team context.
