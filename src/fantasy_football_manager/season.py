"""Weekly lineup assignments and roster proposals. These functions do not submit actions."""

from __future__ import annotations

from datetime import datetime, timezone
from math import inf, isfinite

from .models import LeagueSnapshot, ManagerConfig, Player, Team


_UNAVAILABLE = {"OUT", "IR", "INJURED_RESERVE", "INJURED RESERVE", "PUP", "SUSPENDED", "EXEMPT", "INACTIVE"}
_OBJECTIVES = {"projected_points": "weekly_projection", "floor": "weekly_floor", "upside": "weekly_ceiling"}


def _source(snapshot: LeagueSnapshot, config: ManagerConfig) -> dict:
    age = snapshot.age_seconds()
    stamp = snapshot.source.projections_observed_at
    projection_age = None if stamp is None else max(0, (datetime.now(timezone.utc) - stamp).total_seconds())
    return {
        "provider": snapshot.source.provider,
        "observed_at": snapshot.source.observed_at.isoformat(),
        "age_seconds": round(age, 3),
        "projections_observed_at": None if stamp is None else stamp.isoformat(),
        "projection_age_seconds": None if projection_age is None else round(projection_age, 3),
        "complete": snapshot.source.complete,
        "locks_verified": snapshot.source.locks_verified,
        "synthetic": snapshot.source.synthetic,
        "stale": age > config.limits.max_season_age_seconds,
        "projections_stale": projection_age is not None and projection_age > config.limits.max_season_age_seconds,
    }


def _base(snapshot: LeagueSnapshot, config: ManagerConfig) -> dict:
    source = _source(snapshot, config)
    errors = []
    if snapshot.phase != "season":
        errors.append("Weekly recommendations require a season snapshot.")
    if not source["complete"]:
        errors.append("The league snapshot is incomplete.")
    if not source["locks_verified"]:
        errors.append("Player locks are not verified.")
    if source["stale"] or source["projections_stale"]:
        errors.append("The source exceeds the configured age limit.")
    warnings = []
    if source["projections_observed_at"] is None:
        warnings.append("The weekly projection timestamp is unknown.")
    return {"status": "incomplete" if errors else "ok", "week": snapshot.week,
            "source": source, "errors": errors, "warnings": warnings}


def _usable(player: Player, snapshot: LeagueSnapshot) -> bool:
    return player.availability not in _UNAVAILABLE and player.bye != snapshot.week


def _score(player: Player, field: str) -> float | None:
    value = getattr(player, field)
    return float(value) if value is not None and isfinite(value) else None


def _assignment(cost: list[list[float]]) -> list[int] | None:
    """Solve a rectangular minimum-cost assignment with forbidden edges."""
    rows = len(cost)
    if not rows:
        return []
    columns = len(cost[0])
    if columns < rows:
        return None
    u, v = [0.0] * (rows + 1), [0.0] * (columns + 1)
    matched, previous = [0] * (columns + 1), [0] * (columns + 1)
    for row in range(1, rows + 1):
        matched[0] = row
        column = 0
        distance, visited = [inf] * (columns + 1), [False] * (columns + 1)
        while True:
            visited[column] = True
            active_row = matched[column]
            delta, next_column = inf, 0
            for other in range(1, columns + 1):
                if visited[other]:
                    continue
                reduced = cost[active_row - 1][other - 1] - u[active_row] - v[other]
                if reduced < distance[other]:
                    distance[other], previous[other] = reduced, column
                if distance[other] < delta:
                    delta, next_column = distance[other], other
            if not isfinite(delta):
                return None
            for other in range(columns + 1):
                if visited[other]:
                    u[matched[other]] += delta
                    v[other] -= delta
                else:
                    distance[other] -= delta
            column = next_column
            if matched[column] == 0:
                break
        while column:
            predecessor = previous[column]
            matched[column] = matched[predecessor]
            column = predecessor
    assignment = [-1] * rows
    for column in range(1, columns + 1):
        if matched[column]:
            assignment[matched[column] - 1] = column - 1
    return assignment


def _total(lineup: dict, slots: dict, players: dict[str, Player], field: str,
           allow_empty: bool = False) -> float | None:
    values = []
    for slot in slots:
        if allow_empty and lineup.get(slot) is None:
            continue
        player = players.get(lineup.get(slot))
        value = None if player is None else _score(player, field)
        if value is None:
            return None
        values.append(value)
    return sum(values)


def _lineup(snapshot: LeagueSnapshot, config: ManagerConfig, team: Team,
            roster_ids: list[str] | None = None, allow_empty: bool = False) -> dict:
    players = {p.id: p for p in snapshot.players}
    slots = snapshot.rules.lineup_slots()
    roster_ids = list(team.roster_ids if roster_ids is None else roster_ids)
    field = _OBJECTIVES[config.strategy.season]
    fixed = {slot: pid for slot, pid in team.lineup.items()
             if pid is not None and players[pid].locked}
    candidates = [players[pid] for pid in sorted(roster_ids)
                  if (not players[pid].locked and _usable(players[pid], snapshot))
                  and any(set(players[pid].eligible_positions).intersection(eligible)
                          for slot, eligible in slots.items() if slot not in fixed)]
    required = candidates + [players[pid] for pid in fixed.values()]
    missing = [{"player_id": p.id, "fields": [key for key in dict.fromkeys(("weekly_projection", field))
                if _score(p, key) is None]} for p in required]
    missing = [item for item in missing if item["fields"]]
    result = {"status": "ok", "team_id": team.id, "team_name": team.name,
              "strategy": config.strategy.season, "objective_field": field,
              "lineup": {}, "projected_points": None, "objective_points": None,
              "current_points": _total(team.lineup, slots, players, "weekly_projection"),
              "current_projected_points": _total(team.lineup, slots, players, "weekly_projection"),
              "improvement": None, "missing_projections": missing, "unfilled_slots": [],
              "errors": [], "warnings": []}
    if missing:
        result.update(status="incomplete", errors=["Required weekly projections are missing."])
        return result
    remaining = [slot for slot in slots if slot not in fixed]
    # A vacancy has no player score. Prefer more filled slots before their scores.
    fill_bonus = 1 + 2 * sum(abs(_score(p, field)) for p in candidates) if allow_empty else 0
    cost = [[-_score(p, field) - fill_bonus if set(p.eligible_positions).intersection(slots[slot]) else inf
             for p in candidates] for slot in remaining]
    if allow_empty:
        cost = [row + [0.0] * len(remaining) for row in cost]
    selected = _assignment(cost)
    if selected is None:
        result.update(status="incomplete", errors=["The available roster cannot fill every legal starter slot."])
        return result
    lineup = dict(fixed)
    lineup.update({slot: candidates[column].id if column < len(candidates) else None
                   for slot, column in zip(remaining, selected)})
    result["lineup"] = {slot: lineup[slot] for slot in slots}
    result["unfilled_slots"] = [slot for slot, pid in lineup.items() if pid is None]
    result["projected_points"] = _total(lineup, slots, players, "weekly_projection", allow_empty)
    result["objective_points"] = _total(lineup, slots, players, field, allow_empty)
    if result["unfilled_slots"]:
        result.update(status="incomplete", errors=["The roster has vacant starter slots."])
    if result["current_points"] is not None:
        result["improvement"] = result["projected_points"] - result["current_points"]
    else:
        result["warnings"].append("The current lineup is incomplete or has missing weekly projections.")
    for pid in fixed.values():
        if not _usable(players[pid], snapshot):
            result["warnings"].append(f"Locked player {pid} remains in the current slot despite unavailable status.")
    uncertain = [pid for pid in lineup.values() if pid is not None and players[pid].availability not in {"ACTIVE", "HEALTHY"}]
    result["availability_flags"] = [{"player_id": pid, "availability": players[pid].availability} for pid in uncertain]
    return result


def recommend_lineup(snapshot: LeagueSnapshot, config: ManagerConfig) -> dict:
    """Return the exact best legal weekly lineup for the selected objective."""
    base = _base(snapshot, config)
    if base["errors"]:
        return {**base, "team_id": snapshot.team_id, "lineup": {}, "projected_points": None,
                "current_points": None, "current_projected_points": None, "improvement": None}
    result = _lineup(snapshot, config, snapshot.own_team())
    return {**base, **result, "warnings": base["warnings"] + result["warnings"]}


def _move_limits(snapshot: LeagueSnapshot, config: ManagerConfig) -> tuple[dict, list[str]]:
    budget, limits = snapshot.budget, config.limits
    if budget is None or budget.pending_moves is None or budget.pending_amount is None:
        return {}, ["Current move counts, FAAB balance, and pending commitments must be known."]
    moves = limits.max_weekly_moves - budget.roster_moves_week - budget.pending_moves
    bid = max(0, min(limits.faab_per_claim,
                     limits.faab_per_week - budget.spent_week - budget.pending_amount,
                     limits.faab_per_season - budget.spent_season - budget.pending_amount,
                     budget.balance - limits.faab_reserve - budget.pending_amount))
    return {"remaining_weekly_moves": max(0, moves), "maximum_faab_bid": bid}, []


def rank_waivers(snapshot: LeagueSnapshot, config: ManagerConfig, limit: int = 10) -> dict:
    """Rank unique add/drop proposals without submitting claims or guessing bid odds."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("The result limit must be an integer from 1 through 100.")
    result = _base(snapshot, config)
    result.update({"strategy": config.strategy.waiver, "recommendations": [], "candidates": [],
                   "missing_projections": [], "baseline_projected_points": None,
                   "bid_win_probability": None, "platform_claim_status_verified": False})
    if result["errors"]:
        return result
    effective, errors = _move_limits(snapshot, config)
    result["effective_limits"] = effective
    if errors:
        result.update(status="incomplete", errors=errors)
        return result
    if effective["remaining_weekly_moves"] == 0:
        result.update(status="blocked", errors=["The configured weekly move limit has been reached."])
        return result
    team = snapshot.own_team()
    baseline = _lineup(snapshot, config, team, allow_empty=True)
    result["baseline_projected_points"] = baseline["projected_points"]
    result["baseline_unfilled_slots"] = baseline["unfilled_slots"]
    if baseline["missing_projections"]:
        result.update(status="incomplete", errors=baseline["errors"], missing_projections=baseline["missing_projections"])
        return result
    if baseline["unfilled_slots"]:
        result["warnings"].append("Vacant baseline slots contribute zero points. No player projection is replaced with zero.")
    players = {p.id: p for p in snapshot.players}
    owned = {pid for t in snapshot.teams for pid in t.roster_ids + t.reserve_ids}
    limits = config.limits
    droppable = [pid for pid in sorted(team.roster_ids) if pid not in limits.protected_ids
                 and not players[pid].locked
                 and (limits.drop_mode == "any_unprotected" or pid in limits.allowed_drop_ids)]
    drop_options = ([None] if len(team.roster_ids) < snapshot.rules.roster_size else []) + droppable
    output = []
    for candidate in sorted(snapshot.players, key=lambda p: p.id):
        if candidate.id in owned or candidate.locked or not _usable(candidate, snapshot):
            continue
        if not any(set(candidate.eligible_positions).intersection(v) for v in snapshot.rules.lineup_slots().values()):
            continue
        required = {"weekly_projection", _OBJECTIVES[config.strategy.season]}
        if config.strategy.waiver == "bench_upside":
            required.add("weekly_ceiling")
        missing = [field for field in sorted(required) if _score(candidate, field) is None]
        if missing:
            result["missing_projections"].append({"player_id": candidate.id, "fields": missing})
            continue
        alternatives = []
        for drop_id in drop_options:
            proposed = [pid for pid in team.roster_ids if pid != drop_id] + [candidate.id]
            if any(sum(players[pid].position == pos for pid in proposed) > cap
                   for pos, cap in snapshot.rules.caps.items()):
                continue
            if snapshot.rules.caps.get(candidate.position, 0) == 0:
                continue
            after = _lineup(snapshot, config, team, proposed)
            if after["status"] != "ok":
                continue
            improvement = after["projected_points"] - baseline["projected_points"]
            if improvement + 1e-9 < limits.min_lineup_improvement:
                continue
            upside_gain = None
            if config.strategy.waiver == "bench_upside":
                old_ceiling = 0.0 if drop_id is None else _score(players[drop_id], "weekly_ceiling")
                if old_ceiling is None:
                    result["missing_projections"].append({"player_id": drop_id, "fields": ["weekly_ceiling"]})
                    continue
                upside_gain = candidate.weekly_ceiling - old_ceiling
            alternatives.append({"add_player_id": candidate.id, "add_player_name": candidate.name,
                                 "drop_player_id": drop_id, "lineup": after["lineup"],
                                 "projected_points": after["projected_points"],
                                 "improvement": improvement, "weekly_upside_gain": upside_gain,
                                 "maximum_faab_bid": effective["maximum_faab_bid"],
                                 "suggested_bid": None, "bid_win_probability": None})
        if alternatives:
            def rank(item):
                primary = item["weekly_upside_gain"] if config.strategy.waiver == "bench_upside" else item["improvement"]
                return (-primary, -item["improvement"], item["drop_player_id"] is not None, item["drop_player_id"] or "")
            output.append(sorted(alternatives, key=rank)[0])
    output.sort(key=lambda item: (-(item["weekly_upside_gain"] if config.strategy.waiver == "bench_upside" else item["improvement"]),
                                  -item["improvement"], item["add_player_id"]))
    result["recommendations"] = output[:limit]
    result["candidates"] = output[:limit]
    if baseline["unfilled_slots"] and not output:
        result.update(status="incomplete", errors=["No single acquisition meets every lineup and action limit."])
    if result["missing_projections"]:
        unique = {(item["player_id"], tuple(item["fields"])): item for item in result["missing_projections"]}
        result["missing_projections"] = list(unique.values())
        result["status"] = "incomplete"
        result["warnings"].append("The ranking excludes candidates with missing weekly inputs.")
    if config.strategy.waiver == "conserve_faab":
        result["warnings"].append("Prefer a free acquisition when platform rules permit it. No FAAB bid is estimated.")
    result["warnings"].append("These are alternative single acquisitions, not a combined claim plan.")
    result["warnings"].append("Unrostered status does not establish immediate free-agent or waiver eligibility.")
    return result


def power_rankings(snapshot: LeagueSnapshot, config: ManagerConfig) -> dict:
    """Compare legal weekly lineups. These values are not championship probabilities."""
    result = _base(snapshot, config)
    result.update({"rankings": [], "basis": "optimal_legal_weekly_lineup", "championship_odds": None})
    if result["errors"]:
        return result
    entries = [_lineup(snapshot, config, team) for team in snapshot.teams]
    complete = all(entry["status"] == "ok" for entry in entries)
    entries.sort(key=lambda entry: (entry["projected_points"] is None,
                                    -(entry["projected_points"] or 0), entry["team_id"]))
    previous_points, previous_rank = None, 0
    for index, entry in enumerate(entries, 1):
        if complete:
            if entry["projected_points"] != previous_points:
                previous_rank = index
            entry["rank"] = previous_rank
            previous_points = entry["projected_points"]
        else:
            entry["rank"] = None
    if not complete:
        result.update(status="incomplete", errors=["Complete league ranks require weekly lineups for every team."])
    result["rankings"] = entries
    return result
