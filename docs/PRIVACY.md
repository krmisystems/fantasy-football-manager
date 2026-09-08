# Privacy notes

The service runs locally over STDIO.
Its default data directory is outside the source checkout.
`FFM_DATA_DIR` and `--data-dir` can select a different directory.

The local store can contain league rules, players, rosters, budgets, proposals, and action history.
The server returns requested records and calculations to its connected MCP client.
That client controls any further transmission or retention of the conversation and tool results.

Version 0.1 has no live provider login or live roster write adapter.
The examples and demo use synthetic data.
The repository must not contain real league captures, account identifiers, credentials, or runtime databases.

Keep backups and exported personal data in a private location.
The `.gitignore` file excludes common runtime files. It cannot identify every possible personal export.
Review the files selected for a commit or release.

This document describes the local source package. It does not describe a hosted service or promise a hosting provider's retention policy.
