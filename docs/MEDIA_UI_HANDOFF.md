# Media UI integration prompt

Use this prompt in the agent session that owns the existing media interface.
It requires discovery of that application's actual framework, authentication, and deployment.
It does not assume a hostname, filesystem path, or private network layout.

```text
Integrate the Fantasy Football Manager portfolio into this home server's existing media UI.

First inspect this application's code, instructions, authentication, routing, and deployment.
Locate the installed Fantasy Football Manager source and private coordinator manifest.
Read docs/PORTFOLIO.md and docs/PORTFOLIO_VALIDATION.md from its reviewed source revision.
Do not assume that a published PyPI version includes this dashboard.
Confirm the installed commands and API before connecting the interface.

Add a Fantasy section that shows all configured managed teams.
Include league, sport, provider, source freshness, roster, projections, saved limits, analysis, and proposals.
Provide player search with separate ownership contexts for each league.
Keep missing projections unknown and show stale or incomplete observations.
Separate calculated recommendations, pending proposals, queued waivers, and confirmed transactions.
Label demo data clearly. Never substitute demo results for missing live data.

Use the packaged Fieldroom dashboard through an authenticated same-origin proxy when practical.
The dashboard uses relative asset and API paths for a mounted prefix.
Alternatively, build native media UI components against the same documented API.
Choose the option that fits the inspected application and preserves its design.

Run fantasy-football-dashboard as a separate restricted service on loopback.
Use the existing private coordinator manifest and protected ESPN credential file.
Use the same credential directory as the coordinator to preserve the shared team lease.
Do not change the current season coordinator, automation policy, or per-team limits.
Do not restart or replace the production worker solely to install the UI.
Use an isolated environment if the reviewed dashboard package differs from the worker package.

The dashboard accepts --manifest, --credential-file, --port, and --enable-actions.
Its environment alternatives are FFM_PORTFOLIO_MANIFEST and FFM_ESPN_CREDENTIAL_FILE.
Keep all values in private service configuration outside GitHub.
Bind the upstream service to 127.0.0.1. Do not expose it directly to the LAN or internet.

Protect every proxy route, including static assets and /api/session, with existing authentication.
Require an authorized user role for all approval and submission requests.
Validate the incoming browser Origin and the application's CSRF protection before forwarding writes.
Reject unauthenticated, cross-origin, and unauthorized write requests at the media backend.
Only then rewrite upstream Host and Origin to the dashboard's exact loopback authority.
Preserve the dashboard CSRF token and exact review/submit JSON bodies.
Never use an unrestricted URL proxy. Fix the upstream destination in trusted configuration.
Use a prefix with a trailing slash and strip it before forwarding upstream paths.
Preserve same-origin frame restrictions if embedding the dashboard.
Do not add wildcard CORS or disable either service's request validation.

Include exact-proposal review and explicit final approval/submission controls.
Use the dashboard's own approval flow and one-use review token.
Do not implement a second ESPN client or bypass the existing policy and reconciliation service.
Show a busy lease, stale proposal, changed policy, expired session, or uncertain result clearly.
Do not retry a transaction after an uncertain response.
The UI may submit existing HTTP season proposals. It does not submit browser draft picks.
Preserve the project's existing draft tools.

Validate with fictional fixtures before using the real manifest.
Test all team selectors, player filters, proposal details, and mobile layouts.
Test unauthorized reads and writes, CSRF rejection, exact approval, expired tokens, and duplicate clicks.
Test a changed roster or policy between review and submission.
Test pending-waiver and uncertain-result displays without claiming confirmed ownership.
Verify proxy paths, assets, security headers, and browser console health.
Read all actual team summaries without changing live rosters or policies.
Do not perform a live transaction solely as a UI test.

Capture sanitized screenshots and document the installed source revision, service, tests, and rollback command.
Keep server names, local paths, league identifiers, personal team names, and credentials out of public artifacts.
Document Verified, Planned, and Not Tested results separately.
Report any missing information before making assumptions that affect deployment or authentication.
```
