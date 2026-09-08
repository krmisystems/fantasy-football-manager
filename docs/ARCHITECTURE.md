# Architecture

Two local STDIO servers share policy and versioned SQLite state.
The manager provides calculations and synthetic execution.
The ESPN companion provides browser observations, live draft submissions, and verified weekly lineup swaps.

```mermaid
flowchart TD
    Client[MCP client and three workflow skills] --> Manager[Manager MCP]
    Client --> ESPN[ESPN companion MCP]
    Import[JSON import or synthetic demo] --> Manager
    Manager --> Store[Versioned SQLite state and saved policy]
    ESPN --> Store
    ESPN --> Worker[Continuous loop or standalone worker]
    Worker --> Browser[Playwright browser adapter]
    Browser --> Chrome[Dedicated Chrome profile or local CDP]
    Chrome --> Platform[ESPN authenticated reads and team pages]
    Browser --> Validate[Complete observation and history validation]
    Validate --> Store
    Store --> Draft[Two-pick Monte Carlo estimates]
    Store --> Season[Weekly lineup and waiver analysis]
    Draft --> Worker
    Season --> Worker
    Worker --> Claim[Policy and durable one-click claim]
    Claim --> Browser
    Browser --> Reconcile[Observed pick or lineup reconciliation]
    Reconcile --> Store
    Manager --> Demo[Synthetic execution adapter]
    Demo --> Store
```

## State and estimates

A snapshot identifies its league, team, season, week, source, and observation time.
Validation checks unique players, ownership, draft order, roster rules, and browser identity.
Changed decision inputs receive a revision. Timestamp-only refreshes retain that revision.
Configuration changes receive a separate revision.
Both servers must share a data directory to coordinate the same league context.

The draft model compares the next two selections.
Strategy weights change preferences without changing supplied projections or hard roster requirements.
Matching batches combine score sums and conditional availability counts.
Changed inputs reset the aggregate. Stale state and failed observations suppress outdated recommendations.
More trials cannot repair a wrong projection or missing pick.

Weekly calculations require weekly projections and preserve locked assignments.
Season totals are not divided into invented weekly forecasts.
Floor and upside objectives sum supplied player bounds. Those sums are not team outcome percentiles.

## Live draft claim and verification

```mermaid
sequenceDiagram
    participant Client as MCP client or automatic loop
    participant Service as ESPN service
    participant Store as SQLite state
    participant Browser as Browser adapter
    participant ESPN as ESPN draft room
    Client->>Service: Prepare exact player
    Service->>Browser: Observe complete current board
    Browser-->>Service: Validated observation
    Service->>Store: Save proposal and exact baseline
    Client->>Service: Submit proposal with required authorization
    Service->>Browser: Check room and visible pick
    Service->>Store: Recheck revisions and policy
    Service->>Store: Claim awaiting_verification atomically
    Service->>Browser: Grant one click permit
    Browser->>Service: Validate permit immediately before click
    Browser->>ESPN: Click the exact player once
    Browser->>ESPN: Read resulting draft state
    Browser-->>Service: Complete platform observation
    Service->>Store: Commit actual picks and settled result
    Service-->>Client: Return saved result
```

Review mode requires confirmation of the exact proposal.
Automatic mode uses saved authorization and limits.
Neither mode bypasses stale data, changed configuration, caps, or unresolved claims.
A timeout leaves the claim awaiting verification. Repeated submission cannot grant another click.
Missing expected picks do not create phantom roster entries.

The manager's separate execution tools remain restricted to synthetic state.
Season mode uses a separate durable lineup proposal and verifies each swap.
It checks the exact incoming player and destination occupant before the confirmation click.
Reconciliation compares occupant sets within equivalent slot groups. RB slot order alone does not change a lineup.
Each swap must meet the configured improvement limit. A target can require intermediate moves that fail that limit.
One confirmed swap does not establish that the full optimized lineup was applied.
Live waivers, acquisitions, drops, and trades have no adapter in this version.

## Runtime lifetime

The ordinary ESPN loop belongs to its MCP process.
A standalone worker uses the saved connection and policy in a separate process.
It can continue after Codex closes. Draft mode stops when the selected roster is complete.
Season mode continues for the explicit connected week. Automatic week rollover remains planned.
A shared pause flag blocks new actions across workers using the same data directory.
The profile lease prevents simultaneous ownership of that profile.

Saved state and proposals survive normal restarts through SQLite.
The worker is not an operating-system service and has no automatic reboot recovery.
Packaged draft and lineup submission still need end-to-end acceptance tests in an authenticated ESPN league.
