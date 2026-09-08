# Server deployment templates

These files use generic accounts and paths. Adapt them in private server configuration.
Do not commit server addresses, authentication data, or private manifests.

## Season coordinator

Run the coordinator from the installed Python environment:

```sh
python -m fantasy_football_manager.server --manifest /etc/fantasy-football/leagues.json --interval 60
```

Use `--once` for one sweep. Use `--health` to read saved health without opening Chrome.
Both checks return a nonzero exit code when the required observations are unavailable or stale.
The health command also requires an active coordinator heartbeat.

The private manifest contains `browser_data_dir`, optional `status_file`, `headless`, and `leagues`.
Each league requires `league_id`, `team_id`, `season`, `week`, and `data_dir`.
Optional fields are `enabled`, `phase: "season"`, and `mode`.
The supported mode values are `existing`, `advisory`, `review`, and `automatic`.
An explicit mode must match the saved manager config. The manifest cannot change that config.
Relative paths resolve against the manifest directory. Restart the coordinator after manifest changes.

Each visit opens the same server browser profile, observes one league, and performs at most one policy-approved lineup swap.
The coordinator closes that browser before visiting the next league.
Each league keeps its own SQLite database. Weeks remain explicit.
Use a dedicated draft worker for draft automation. A busy browser profile blocks a season sweep.

SIGTERM and SIGINT prevent new actions. The current authorized operation can finish before the browser closes.
An unresolved submission remains in SQLite. A later visit reconciles it before another action.
The service template allows 180 seconds for shutdown. A forced kill cannot guarantee browser cleanup.

Install Chrome and authenticate its dedicated profile on the server before unattended visits.
Set `headless: false` only when the service has a working display, such as a separately managed Xvfb display.
The environment template hook can supply `DISPLAY`. The coordinator does not create an authentication session.

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
Keep all backup sets outside the repository. Browser authentication profiles are excluded.
After a restore, stop other controllers and reconcile pending submissions before enabling new actions.

The default retention is 14 days. Retention applies only to complete, recognized `ffm-backup-*` sets in the selected output directory.
Unexpected files or subdirectories prevent deletion of that set.
Failed backups do not prune previous sets.

The systemd archive timer runs once per minute. The backup timer runs daily.
The templates do not install accounts, PostgreSQL, Chrome, or authentication profiles.
Verify service startup, graceful stop, restore, and operation without the PC on the actual server.
