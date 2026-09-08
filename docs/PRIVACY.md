# Privacy notes

Both MCP servers run locally over STDIO.
They share a data directory that defaults to a location outside the source checkout.
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

Keep the data directory, profile, logs, and real league exports out of Git and release archives.
The repository examples and test fixtures use fictional data.
The release validator rejects known profile paths and private runtime file names.
Pattern checks cannot identify every personal export. Review selected artifacts before publication.

Use separate private directories for separate active league contexts when needed.
Both servers and the worker must use the same directory to share policy and pause state.
Deleting runtime data can remove saved authentication and unresolved action records.
