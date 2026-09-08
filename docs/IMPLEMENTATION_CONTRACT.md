# Implementation contract

This file coordinates the first implementation. All public examples must be synthetic.

## Shared models

Root owns `models.py`, `policy.py`, `store.py`, `mcp_server.py`, package metadata, and integration tests.
Other modules receive validated `LeagueSnapshot` and `ManagerConfig` objects from `models.py`.
Their calculations must not modify supplied objects.

`LeagueSnapshot` fields:
- `schema_version=1`, `league_id`, `team_id`, `season`, `week`.
- `source`: `provider`, UTC `observed_at`, `complete`, `locks_verified`, `synthetic`.
- `rules`: `teams`, `slot`, `rounds`, `snake`, `starters` count mapping, `caps` mapping, `flex_eligible` list.
- `players`: player objects with `id`, `name`, `position`, `eligible_positions`, NFL `team`, season `projection`, optional `weekly_projection`, `weekly_floor`, `weekly_ceiling`, `adp`, `availability`, `locked`, optional `bye`.
- `teams`: `id`, `name`, snake `slot`, `roster_ids`, current `lineup` mapping.
- `picks`: `pick_no`, `player_id`, `slot`.
- optional `budget`: `balance`, `spent_week`, `spent_season`, nullable `pending_amount`, nullable `pending_moves`, `roster_moves_week`.

Lineup slot names are `QB1`, `RB1`, `RB2`, `WR1`, `WR2`, `TE1`, `FLEX1`, `DST1`, `K1` for the default rules.
Use configured starter counts. Every player can fill at most one slot.
Players in the user's roster are selected by `snapshot.team_id`.
Every player has one primary position and can have additional eligible positions.
Source observation age and weekly projection completeness must remain visible.
Snapshot validators reject duplicate ownership, duplicate picks, gaps, wrong snake owners, and unknown players.

`ManagerConfig` fields:
- `automation`: `preset` (advisory/review/bounded_automation/custom), `paused`, `actions` mapping to disabled/advisory/review/automatic.
- `limits`: protected IDs, `drop_mode` listed_only/any_unprotected, allowed drop IDs, maximum weekly moves, FAAB per-claim/week/season caps, reserve, minimum lineup improvement, draft/season source-age limits, optional `max_adp_reach`, batch trials.
- `strategy`: `draft` (balanced_value/rb_priority/wr_priority/hero_rb/zero_rb), `season` (projected_points/floor/upside), `waiver` (immediate_starter/bench_upside/conserve_faab).

## Module assignments

`draft.py`: `recommend_draft(snapshot, config, trials=40, seed=1) -> dict`; configurable strategy affects ranking, not hard rules. Reuse the tested legacy engine in a namespaced module. Expose honest simulation metadata. Optional runtime class can remain root-owned.

`season.py`: `recommend_lineup(snapshot, config) -> dict`, `rank_waivers(snapshot, config, limit=10) -> dict`, `power_rankings(snapshot, config) -> dict`. Use weekly projections and enforce locked existing assignments. Missing inputs produce an explicit error or incomplete result, never fabricated values. Result includes `lineup` mapping, `projected_points`, current points and `improvement` where calculable.

Root provides durable SQLite state, revision checks, bounded worker jobs, action proposals, synthetic-only execution, and MCP tools.
Live provider writes are unsupported in version 0.1.0. Automation can be exercised against synthetic data.
Advisory/review/automatic settings must report the effective supported capability.

## Testing

Each module owns its test file. Use direct model construction or a module-local fixture.
Root will supply a complete synthetic demo after models exist.
Do not read private draft files in tests or copy real account, league, or roster data.
