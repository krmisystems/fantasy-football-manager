# Server deployment templates

These files use generic accounts and paths. Adapt them in private server configuration.
Do not commit server addresses, authentication data, or private manifests.
They describe the unpublished v0.4.0 candidate. Existing v0.3.3 acceptance records remain historical.
These templates do not establish live transaction acceptance.

## HTTP season coordinator

The coordinator defaults to `transport: "http"` and `auto_rollover: true`.
HTTP season operation requires neither Chrome, Playwright, Xvfb, nor a display.
Install the base source environment, or add `--extra server` for the PostgreSQL archive.
Copy [leagues.http.example.json](leagues.http.example.json) to a private manifest before editing it.
The example entries are disabled and use fictional league identifiers.

Run the coordinator from the installed Python environment:

```sh
python -m fantasy_football_manager.server --manifest /etc/fantasy-football/leagues.json --interval 60
```

Use `--once` for one sweep. It can submit actions under saved automatic permissions.
For observations only, save the shared pause in each selected manager configuration before the sweep.
Use `--health` to read saved health without an ESPN request or browser operation.
Both checks return a nonzero exit code when the required observations are unavailable or stale.
The health command also requires an active coordinator heartbeat.

The private manifest contains the following top-level fields:

| Field | Current behavior |
| --- | --- |
| `browser_data_dir` | Required path for the coordinator lease. Browser mode also uses it for the profile. |
| `status_file` | Optional JSON health path. The default is `season-status.json` beside the manifest. |
| `transport` | `http` by default. `browser` explicitly selects the legacy season adapter. |
| `credential_file` | Optional protected ESPN session-file path. HTTP also accepts `FFM_ESPN_CREDENTIAL_FILE`. |
| `auto_rollover` | True by default. HTTP follows ESPN's verified current period. |
| `headless` | True by default. This affects browser mode only. |
| `leagues` | At least one configured context. Each context keeps separate manager state. |

Each league requires `league_id`, `team_id`, `season`, `week`, and `data_dir`.
Optional fields are `enabled`, `phase: "season"`, and `mode`.
The supported mode values are `existing`, `advisory`, `review`, and `automatic`.
An explicit mode must match saved `set_lineup` permission. The manifest cannot change that permission.
Acquisitions, drops, and IR use their own saved action modes and limits.
Relative paths resolve against the manifest directory. Restart the coordinator after manifest changes.

Each HTTP visit verifies ownership, period, targeted locks, bye weeks, pending claims, and applicable budgets.
It submits at most one transaction that passes policy before closing the connection.
An acquisition and a later starter assignment require separate confirmed transactions.
Unknown projections remain unknown. Coverage repairs require named player authorization in saved limits.

Each league keeps its own SQLite database.
With rollover enabled, pending waivers and unresolved submissions retain their original week.
Backward or unverified periods stop rollover. Set `auto_rollover: false` to retain the requested week.
Direct MCP connections have a separate false default for rollover.

Provision a protected session file before enabling HTTP visits.
The file contains only `SWID` and `espn_s2`. Keep its contents outside manifests, command lines, and tool arguments.
The service account must own the Linux file with mode `0600`.
Its private parent directory must use mode `0700` and permit writes by that account for team lease files.
The optional `session-import` extra can import supported Linux Chromium `v10` cookies without starting Chromium.
See [session setup](../docs/PLUGIN_INSTALL.md#configure-an-http-season-session-unreleased) for the exact command and limitations.
An expired session requires renewed authorized credentials. The coordinator does not perform password sign-in.

Use one protected credential directory for controllers that share an account.
A team lease blocks concurrent HTTP control of the same league and team through that directory.
Different teams can hold separate leases. Unrelated copies of credentials do not share the lease.
The coordinator also prevents duplicate sweeps through its `browser_data_dir` lease.

SIGTERM and SIGINT prevent new actions. The current authorized operation can finish before the connection closes.
An unresolved submission remains in SQLite. A later visit reconciles it before another action.
The service template allows 180 seconds for shutdown. A forced kill cannot guarantee a completed observation or reconciliation.
An uncertain HTTP result never permits a duplicate POST or replacement proposal.
`pending_waiver` identifies a queued claim and does not prove ownership.
`not_submitted` proves that preflight ended before the transaction request began.

The [season service template](systemd/fantasy-football-season.service) has no display dependency.
Copy actual account, file, and mount settings into private installation files.
Preserve unresolved SQLite claims when replacing a service or moving its data.

## Explicit browser operation

Install the source `browser` extra and Google Chrome for drafts or legacy browser season operation.
Use [leagues.browser.example.json](leagues.browser.example.json) for the legacy season adapter.
It sets `transport: "browser"` and `auto_rollover: false`.
Each browser visit supports one qualifying lineup swap under the saved limits.
A profile lease permits only one controller at a time.

The season coordinator rejects draft entries.
For a draft, save a verified `phase="draft"` connection in a separate manager directory through the ESPN companion.
Complete authorized sign-in in that dedicated browser profile.
Verify the requested team, draft room, and disabled ESPN Autopick before starting automatic picks.
Use [fantasy-football-draft.service](systemd/fantasy-football-draft.service) for that saved draft connection.
Its generic paths select a separate profile and state directory.

Use a visible browser only with an available display. A separately managed Xvfb display is one optional browser setup.
Set any required `DISPLAY` value in a private environment file.
The templates do not create a display or authenticate a browser.
Stop another controller before a worker uses its profile.
HTTP season operation can continue without these browser components.

## Private backup sets

Install `backup.py` with the deployment files. Run it with the application Python environment:

```sh
python /opt/fantasy-football/deployment/backup.py \
  --manifest /etc/fantasy-football/archive.json \
  --output-dir /var/lib/fantasy-football/backups \
  --dsn dbname=fantasy_football \
  --config /etc/fantasy-football/leagues.json \
  --retention-days 14
```

The archive input manifest selects SQLite databases through `sources[].database`.
The helper uses the SQLite backup API. Committed WAL data enters each snapshot.
The helper also runs `pg_dump` in custom format.
It copies the archive manifest and each explicit `--config` file into the private backup set.
Repeat `--config` for additional configuration files.
Use PostgreSQL peer authentication or a protected PostgreSQL service definition.

The helper publishes a set only after every database backup succeeds.
The private `backup.json` lists every dump, SQLite snapshot, and configuration file with its byte count and SHA256 digest.
Each database is internally consistent. The set is not one transaction across all databases.
The backup includes pending submissions and operational state from each selected SQLite database.
The PostgreSQL archive alone cannot replace those databases.

The helper uses private file permissions. Backup metadata contains original paths and private context data.
Keep all backup sets outside the repository.
The helper rejects browser-profile paths. The default template does not select HTTP credentials.
Do not pass the protected session file through `--config`, which copies explicitly selected files.
After a restore, stop other controllers and reconcile pending submissions before enabling new actions.

The default retention is 14 days. Retention applies only to complete, recognized `ffm-backup-*` sets in the selected output directory.
Unexpected files or subdirectories prevent deletion of that set.
Failed backups do not prune previous sets.

The systemd archive timer runs once per minute. The backup timer runs daily.
The templates do not install accounts, dependencies, PostgreSQL, credentials, or browser profiles.
Verify service startup, graceful stop, restore, and operation without the PC on the actual server.
Read the [server guide](../docs/SERVER.md) and [validation status](../docs/VALIDATION.md) before an acceptance claim.
