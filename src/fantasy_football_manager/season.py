"""Weekly lineup assignments and roster proposals. These functions do not submit actions."""

from __future__ import annotations

from datetime import datetime, timezone
from math import inf, isfinite

from .models import LeagueSnapshot, ManagerConfig, Player, Team


_UNAVAILABLE = {"OUT", "DOUBTFUL", "IR", "INJURED_RESERVE", "INJURED RESERVE", "PUP", "SUSPENDED", "EXEMPT", "INACTIVE"}
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
        "locks_scope": snapshot.source.locks_scope,
        "synthetic": snapshot.source.synthetic,
        "stale": age > config.limits.max_season_age_seconds,
        "projections_stale": projection_age is not None and projection_age > config.limits.max_projection_age_seconds,
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


def lineup_delta(before: dict, after: dict, players: dict[str, Player], field: str = "weekly_projection") -> float | None:
    """Compare entering and leaving players. Unchanged players cancel, including unknown scores."""
    previous = {pid for pid in before.values() if pid is not None}
    proposed = {pid for pid in after.values() if pid is not None}
    entering, leaving = proposed - previous, previous - proposed
    values = {pid: _score(players[pid], field) if pid in players else None for pid in entering | leaving}
    if any(value is None for value in values.values()):
        return None
    return sum(values[pid] for pid in entering) - sum(values[pid] for pid in leaving)


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
    # An unavailable current starter still has an unknown baseline when its score is missing.
    required = {p.id: p for p in candidates}
    required.update({pid: players[pid] for pid in team.lineup.values() if pid is not None})
    missing = [{"player_id": p.id, "fields": [key for key in dict.fromkeys(("weekly_projection", field))
                if _score(p, key) is None]} for p in required.values()]
    missing = [item for item in missing if item["fields"]]
    blocking = [item for item in missing if item["player_id"] not in fixed.values()]
    result = {"status": "ok", "team_id": team.id, "team_name": team.name,
              "strategy": config.strategy.season, "objective_field": field,
              "lineup": {}, "projected_points": None, "objective_points": None,
              "current_points": _total(team.lineup, slots, players, "weekly_projection"),
              "current_projected_points": _total(team.lineup, slots, players, "weekly_projection"),
              "improvement": None, "missing_projections": missing, "unfilled_slots": [],
              "blocking_missing_projections": blocking, "comparison_complete": False,
              "projection_complete": False, "comparison_scope": "known_projection_slots" if missing else "full_roster",
              "fixed_slots": fixed,
              "excluded_players": [{"player_id": pid, "availability": players[pid].availability,
                                    "reason": "locked_bench" if players[pid].locked else "unavailable_this_week",
                                    "weekly_projection": players[pid].weekly_projection}
                                   for pid in roster_ids if pid not in fixed.values()
                                   and (players[pid].locked or not _usable(players[pid], snapshot))],
              "errors": [], "warnings": []}
    if blocking:
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
    result["projection_complete"] = result["projected_points"] is not None and result["objective_points"] is not None
    result["comparison_complete"] = True
    if result["unfilled_slots"]:
        result.update(status="incomplete", errors=["The roster has vacant starter slots."])
    if set(team.lineup) == set(slots):
        result["improvement"] = lineup_delta(team.lineup, result["lineup"], players)
    if result["current_points"] is None:
        result["warnings"].append("The current lineup is incomplete or has missing weekly projections.")
    if missing:
        result["warnings"].append("Locked starters remain fixed. Their unknown scores cancel from the comparison, but total points remain unknown.")
    for pid in fixed.values():
        if not _usable(players[pid], snapshot):
            result["warnings"].append(f"Locked player {pid} remains in the current slot despite unavailable status.")
    uncertain = [pid for pid in lineup.values() if pid is not None and players[pid].availability not in {"ACTIVE", "HEALTHY"}]
    result["availability_flags"] = [{"player_id": pid, "availability": players[pid].availability} for pid in uncertain]
    return result


def recommend_lineup(snapshot: LeagueSnapshot, config: ManagerConfig) -> dict:
    """Optimize known weekly scores while preserving locked slots. Report coverage gaps separately."""
    base = _base(snapshot, config)
    coverage = _coverage(snapshot, config, snapshot.own_team())
    if base["errors"]:
        return {**base, "team_id": snapshot.team_id, "lineup": {}, "projected_points": None,
                "current_points": None, "current_projected_points": None, "improvement": None,
                "comparison_complete": False, "projection_complete": False, "coverage": coverage}
    result = _lineup(snapshot, config, snapshot.own_team())
    return {**base, **result, "warnings": base["warnings"] + result["warnings"], "coverage": coverage}


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


def _coverage(snapshot: LeagueSnapshot, config: ManagerConfig, team: Team) -> dict:
    """List current slot gaps and replacement options. These options are not action permits."""
    players = {p.id: p for p in snapshot.players}
    slots = snapshot.rules.lineup_slots()
    current_ids = {pid for pid in team.lineup.values() if pid is not None}
    owned = {pid for other in snapshot.teams for pid in other.roster_ids + other.reserve_ids}
    field = _OBJECTIVES[config.strategy.season]
    base = _base(snapshot, config)
    effective, budget_errors = _move_limits(snapshot, config)
    source_ready = not base["errors"] and snapshot.source.projections_observed_at is not None
    result = {"gaps": [], "candidates": [], "source_ready": source_ready,
              "effective_limits": effective, "budget_errors": budget_errors,
              "platform_eligibility_verified": False, "authorized": False}
    for slot, eligible in slots.items():
        pid = team.lineup.get(slot)
        starter = players.get(pid)
        reasons = []
        if starter is None:
            reasons.append("vacant_slot")
        else:
            if not _usable(starter, snapshot):
                reasons.append("starter_unavailable")
            elif starter.availability not in {"ACTIVE", "HEALTHY"}:
                reasons.append("starter_availability_risk")
            if _score(starter, "weekly_projection") is None or _score(starter, field) is None:
                reasons.append("starter_projection_unknown")
        if not reasons:
            continue
        alternatives = [p for p in snapshot.players if p.id not in current_ids and not p.locked
                        and p.availability in {"ACTIVE", "HEALTHY", "QUESTIONABLE"} and p.bye != snapshot.week
                        and set(p.eligible_positions).intersection(eligible)
                        and _score(p, "weekly_projection") is not None and _score(p, field) is not None
                        and (p.id in team.roster_ids or p.id not in owned)]
        backups = sorted(p.id for p in alternatives if p.id in team.roster_ids)
        if not backups:
            reasons.append("no_projected_bench_cover")
        gap = {"slot": slot, "player_id": pid, "reasons": reasons,
               "locked": bool(starter and starter.locked), "backup_player_ids": backups,
               "availability": starter.availability if starter else None,
               "weekly_projection": starter.weekly_projection if starter else None}
        result["gaps"].append(gap)
        if gap["locked"]:
            continue
        choices = []
        for candidate in alternatives:
            bench = candidate.id in team.roster_ids
            drops = [None] if bench else ([None] if len(team.roster_ids) < snapshot.rules.roster_size else [])
            if not bench:
                drops += [drop_id for drop_id in sorted(team.roster_ids)
                          if drop_id not in config.limits.protected_ids and not players[drop_id].locked
                          and (drop_id not in current_ids or drop_id == pid)
                          and (config.limits.drop_mode == "any_unprotected" or drop_id in config.limits.allowed_drop_ids)]
            for drop_id in drops:
                proposed_ids = team.roster_ids if bench else [roster_id for roster_id in team.roster_ids if roster_id != drop_id] + [candidate.id]
                if len(proposed_ids) > snapshot.rules.roster_size or any(
                    sum(players[roster_id].position == position for roster_id in proposed_ids) > cap
                    for position, cap in snapshot.rules.caps.items()
                ) or snapshot.rules.caps.get(candidate.position, 0) == 0:
                    continue
                proposed_lineup = {key: team.lineup.get(key) for key in slots}
                proposed_lineup[slot] = candidate.id
                blockers = [] if source_ready else ["source_not_ready"]
                if not bench:
                    if budget_errors:
                        blockers.append("budget_unknown")
                    elif effective["remaining_weekly_moves"] == 0:
                        blockers.append("weekly_move_limit")
                    blockers.append("platform_acquisition_eligibility_unverified")
                if pid is not None and pid not in getattr(config.limits, "coverage_repair_ids", []):
                    blockers.append("coverage_repair_not_enabled")
                if any(value is None for value in proposed_lineup.values()):
                    blockers.append("other_vacant_slots")
                choices.append({"slot": slot, "action": "set_lineup" if bench else "acquisition",
                                "player_id": candidate.id, "player_name": candidate.name,
                                "drop_id": drop_id, "repair_player_id": pid,
                                "lineup": proposed_lineup, "weekly_projection": candidate.weekly_projection,
                                "improvement": lineup_delta(team.lineup, proposed_lineup, players),
                                "maximum_faab_bid": None if bench else effective.get("maximum_faab_bid"),
                                "blocking_reasons": blockers, "authorized": False})
        choices.sort(key=lambda item: (-_score(players[item["player_id"]], field),
                                      item["action"] != "set_lineup", item["player_id"],
                                      item["drop_id"] is not None, item["drop_id"] or ""))
        result["candidates"].extend(choices[:10])
    return result


def rank_waivers(snapshot: LeagueSnapshot, config: ManagerConfig, limit: int = 10) -> dict:
    """Rank unique add/drop proposals without submitting claims or guessing bid odds."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("The result limit must be an integer from 1 through 100.")
    result = _base(snapshot, config)
    result.update({"strategy": config.strategy.waiver, "recommendations": [], "candidates": [],
                   "missing_projections": [], "baseline_projected_points": None,
                   "bid_win_probability": None, "platform_claim_status_verified": False,
                   "coverage": _coverage(snapshot, config, snapshot.own_team())})
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
    result["missing_projections"] = list(baseline["missing_projections"])
    if baseline["blocking_missing_projections"]:
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
            improvement = lineup_delta(baseline["lineup"], after["lineup"], players)
            if improvement is None:
                continue
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
        fixed_ids = set(baseline["fixed_slots"].values())
        if any(item["player_id"] not in fixed_ids for item in result["missing_projections"]):
            result["status"] = "incomplete"
            result["warnings"].append("The ranking excludes candidates with missing weekly inputs.")
        else:
            result["warnings"].append("Unknown locked starter scores cancel from acquisition comparisons. Total points remain unknown.")
    if config.strategy.waiver == "conserve_faab":
        result["warnings"].append("Prefer a free acquisition when platform rules permit it. No FAAB bid is estimated.")
    result["warnings"].append("These are alternative single acquisitions, not a combined claim plan.")
    result["warnings"].append("Unrostered status does not establish immediate free-agent or waiver eligibility.")
    return result


def power_rankings(snapshot: LeagueSnapshot, config: ManagerConfig) -> dict:
    """Compare legal weekly lineups. These values are not championship probabilities."""
    result = _base(snapshot, config)
    result.update({"rankings": [], "basis": "optimal_legal_weekly_lineup", "championship_odds": None})
    if snapshot.source.locks_scope != "league":
        result["errors"].append("League rankings require verified player locks for every team. Current lock observations cover only the selected team.")
        result["status"] = "incomplete"
    if result["errors"]:
        return result
    entries = [_lineup(snapshot, config, team) for team in snapshot.teams]
    complete = all(entry["status"] == "ok" and entry["projected_points"] is not None for entry in entries)
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
