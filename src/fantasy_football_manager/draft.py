"""Read-only draft recommendations from validated league snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json

from . import __version__
from . import legacy_engine
from .models import LeagueSnapshot, ManagerConfig


STRATEGY_DESCRIPTIONS = {
    "balanced_value": "Compare roster value above replacement without a position preference.",
    "rb_priority": "Increase RB value by 30 percent. Reduce WR value by 5 percent.",
    "wr_priority": "Increase WR value by 30 percent. Reduce RB value by 5 percent.",
    "hero_rb": "Favor one strong RB. Reduce the value of additional RBs and increase WR value.",
    "zero_rb": "Reduce early RB value. Increase RB value in later rounds.",
}


def _fingerprint(value: dict) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def recommend_draft(snapshot: LeagueSnapshot, config: ManagerConfig,
                    trials: int = 40, seed: int | None = 1) -> dict:
    """Estimate the next two selections. This function does not draft a player.

    Stale or incomplete snapshots produce no recommendations. Strategy weights are
    preferences, not forecasts. The model does not estimate championship odds.
    """
    if snapshot.phase != "draft":
        raise ValueError("Draft analysis requires a draft snapshot.")
    if type(trials) is not int or not 1 <= trials <= 500:
        raise ValueError("Use an integer trial count from 1 to 500.")
    if seed is not None and type(seed) is not int:
        raise ValueError("The simulation seed must be an integer or null.")
    rules = snapshot.rules
    own_team = snapshot.own_team()
    for team in snapshot.teams:
        expected = {pick.player_id for pick in snapshot.picks if pick.slot == team.slot}
        if set(team.roster_ids) != expected or team.reserve_ids:
            raise ValueError("Draft rosters must match the complete pick history. Reserve slots are separate.")
    if any(player.position not in player.eligible_positions for player in snapshot.players):
        raise ValueError("Draft analysis requires each player's primary position to be eligible.")
    opponent_ids = {pick.player_id for pick in snapshot.picks if pick.slot != own_team.slot}
    if any(player.projection is None and player.id not in opponent_ids for player in snapshot.players):
        raise ValueError("Available and selected-team draft players require full-season projections.")

    players = [{"id": player.id, "name": player.name, "position": player.position,
                "team": player.team, "projection": player.projection, "adp": player.adp,
                "injury_status": player.availability, "bye": player.bye}
               for player in snapshot.players]
    picks = [pick.model_dump() for pick in snapshot.picks]
    engine_config = {"teams": rules.teams, "slot": own_team.slot, "rounds": rules.rounds,
                     "snake": rules.snake, "starters": dict(rules.starters),
                     "caps": {pos: rules.caps.get(pos, 0) for pos in legacy_engine.POSITIONS},
                     "bench": rules.bench, "flex_eligible": list(rules.flex_eligible),
                     "strategy": config.strategy.draft, "max_adp_reach": config.limits.max_adp_reach,
                     "candidate_limit": 36}
    current_pick = len(picks) + 1
    future = [number for number in range(current_pick, rules.teams * rules.rounds + 1)
              if legacy_engine.draft_slot(number, rules.teams, rules.snake) == own_team.slot]
    age = snapshot.age_seconds()
    stale = age > config.limits.max_draft_age_seconds
    projections_at = snapshot.source.projections_observed_at
    projection_age = (max(0.0, (datetime.now(timezone.utc) - projections_at).total_seconds())
                      if projections_at is not None else None)
    warnings = []
    if stale:
        warnings.append("The draft snapshot is stale. Refresh the source before choosing a player.")
    if not snapshot.source.complete:
        warnings.append("The source snapshot is incomplete. Obtain the complete draft history.")
    if projections_at is None:
        warnings.append("The projection observation time is not supplied.")
    if any(set(player.eligible_positions) != {player.position} for player in snapshot.players):
        warnings.append("Draft analysis uses primary positions. It does not optimize additional player eligibility.")
    result = {
        "model_version": f"{__version__}:two-pick-strategy-v1", "read_only": True,
        "strategy": config.strategy.draft, "strategy_description": STRATEGY_DESCRIPTIONS[config.strategy.draft],
        "phase": "draft", "status": "ready", "completed": not future,
        "draft_complete": current_pick > rules.teams * rules.rounds,
        "current_pick": current_pick, "my_next_pick": future[0] if future else None,
        "following_pick": future[1] if len(future) > 1 else None,
        "available_count": len(players) - len(picks), "recommendations": [], "blocked_candidates": [],
        "trials": 0, "requested_trials": trials, "seed": seed,
        "snapshot_age_seconds": round(age, 3), "source_observed_at": snapshot.source.observed_at.isoformat(),
        "snapshot_complete": snapshot.source.complete, "stale": stale,
        "projections_observed_at": projections_at.isoformat() if projections_at is not None else None,
        "projection_age_seconds": round(projection_age, 3) if projection_age is not None else None,
        "analysis_fingerprint": _fingerprint({"league_id": snapshot.league_id, "season": snapshot.season,
                                               "team_id": snapshot.team_id, "players": players,
                                               "picks": picks, "config": engine_config}),
        "warnings": warnings, "automation_paused": config.automation.paused,
        "action_mode": config.automation.mode_for("draft_pick"),
        "model_scope": "Estimated roster utility across the next two selections. No championship odds.",
        "score_error_scope": "Monte Carlo sampling error. This is not forecast accuracy.",
    }
    if not future:
        result["status"] = "roster_complete"
        return result
    if not snapshot.source.complete or stale:
        result["status"] = "incomplete_snapshot" if not snapshot.source.complete else "stale_snapshot"
        return result
    if not any(player["projection"] is not None and player["projection"] > 0 for player in players):
        result["status"] = "missing_projections"
        warnings.append("Positive season projections are required for draft analysis.")
        return result

    batch = legacy_engine.run_batch(players, picks, engine_config, trials=trials, seed=seed)
    result.update({key: value for key, value in batch.items() if key != "warnings"})
    result["warnings"] = list(dict.fromkeys(warnings + batch.get("warnings", [])))
    result["score_label"] = "Estimated strategy-adjusted roster utility"
    result["status"] = ("ready" if result["recommendations"] else
                        "blocked_by_limits" if result["blocked_candidates"] else "no_eligible_players")
    draft_round = (future[0] - 1) // rules.teams + 1
    result["strategy_weights"] = {
        pos: {"first_player": legacy_engine.strategy_weight(config.strategy.draft, pos, 0, draft_round, rules.rounds),
              "additional_players": legacy_engine.strategy_weight(config.strategy.draft, pos, 1, draft_round, rules.rounds)}
        for pos in legacy_engine.POSITIONS
    }
    for recommendation in result["recommendations"]:
        recommendation["adp_reach"] = max(0.0, recommendation["adp"] - future[0])
        recommendation["estimate_quality"] = ("provisional" if recommendation["simulation_count"] < 30 else "sampled")
    return result
