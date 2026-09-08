"""Action checks. Strategy preferences never override user limits."""

from collections import Counter
from datetime import datetime, timezone

from pydantic import Field

from .feasibility import roster_can_complete
from .models import ACTIONS, LeagueSnapshot, ManagerConfig, Model, Pick


class PickPayload(Model):
    player_id: str


class LineupPayload(Model):
    lineup: dict[str, str]


class AddPayload(Model):
    player_id: str
    drop_id: str | None = None
    bid: int = Field(default=0, ge=0, strict=True)


class DropPayload(Model):
    player_id: str


class PolicyError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise PolicyError(message)


def parse_payload(action: str, payload: dict) -> dict:
    require(action in ACTIONS, "Unknown action type.")
    models = {"draft_pick": PickPayload, "set_lineup": LineupPayload,
              "waiver_claim": AddPayload, "free_agent_add": AddPayload, "drop_player": DropPayload}
    require(action in models, "This release does not execute trades.")
    return models[action].model_validate(payload).model_dump()


def check_action(snapshot: LeagueSnapshot, config: ManagerConfig, action: str, payload: dict, *, execution_scope="synthetic_demo_only") -> dict:
    payload = parse_payload(action, payload)
    if execution_scope == "synthetic_demo_only":
        require(snapshot.source.synthetic and snapshot.source.provider == "synthetic",
                "Live provider writes require the ESPN MCP service. Demo execution requires a synthetic snapshot.")
    elif execution_scope == "host_browser":
        require(action in {"draft_pick", "set_lineup"}, "This browser execution route supports draft picks and lineup moves only.")
        require(snapshot.source.provider == "espn_browser" and not snapshot.source.synthetic,
                "Browser execution requires live ESPN browser observations.")
        browser = snapshot.source.browser
        require(browser is not None, "The browser observation is missing.")
        if action == "draft_pick":
            require(browser.current_pick == len(snapshot.picks) + 1 and not browser.draft_complete,
                    "The visible draft clock does not match the complete pick history.")
            require(browser.autopick_enabled is False, "ESPN Autopick must be verified disabled before direct submission.")
    else:
        raise PolicyError("Unknown execution scope.")
    require(not config.automation.paused, "Automation is paused.")
    require(snapshot.source.complete, "The source snapshot is incomplete.")
    age_limit = config.limits.max_draft_age_seconds if snapshot.phase == "draft" else config.limits.max_season_age_seconds
    require(snapshot.age_seconds() <= age_limit, "The source snapshot is stale. Import a fresh observation.")
    if action in {"set_lineup", "waiver_claim", "free_agent_add", "draft_pick"}:
        stamp = snapshot.source.projections_observed_at
        require(stamp is not None, "The projection observation time must be known.")
        require((datetime.now(timezone.utc) - stamp).total_seconds() <= config.limits.max_projection_age_seconds,
                "The projections are stale. Import fresh projections.")
    mode = config.automation.mode_for(action)
    modes = [mode]
    if action in {"waiver_claim", "free_agent_add"} and payload.get("drop_id"):
        modes.append(config.automation.mode_for("drop_player"))
    require(all(value not in {"disabled", "advisory"} for value in modes),
            "Every part of this action must use review or automatic mode.")
    mode = "review" if "review" in modes else "automatic"
    players = {p.id: p for p in snapshot.players}
    team = snapshot.own_team()
    limits = config.limits

    def drop_check(pid):
        require(pid in team.roster_ids, "The drop player is not on the active roster.")
        require(pid not in limits.protected_ids, "The drop player is protected.")
        require(limits.drop_mode == "any_unprotected" or pid in limits.allowed_drop_ids,
                "The drop player is not on the allowed drop list.")
        require(not players[pid].locked, "A locked player cannot be dropped.")

    if action == "draft_pick":
        require(snapshot.phase == "draft", "Draft picks require a draft snapshot.")
        next_pick = len(snapshot.picks) + 1
        require(next_pick <= snapshot.rules.teams * snapshot.rules.rounds, "The draft is complete.")
        rnd, offset = divmod(next_pick - 1, snapshot.rules.teams)
        owner = snapshot.rules.teams - offset if snapshot.rules.snake and rnd % 2 else offset + 1
        require(owner == team.slot, "It is not the selected team's turn.")
        pid = payload["player_id"]
        require(pid in players, "Unknown player.")
        require(pid not in {p.player_id for p in snapshot.picks}, "The player was already drafted.")
        require(players[pid].availability in {"ACTIVE", "HEALTHY", "QUESTIONABLE"},
                "The player is not confirmed available.")
        if limits.max_adp_reach is not None:
            require(players[pid].adp - next_pick <= limits.max_adp_reach, "The pick exceeds the ADP reach limit.")
        roster = team.roster_ids + [pid]
        require(roster_can_complete(snapshot, roster), "This pick prevents completion of the starting lineup.")
        require(Counter(players[p].position for p in roster)[players[pid].position] <= snapshot.rules.caps.get(players[pid].position, 0),
                "The pick exceeds the position cap.")
    else:
        require(snapshot.phase == "season", "Season actions require a season snapshot.")
        require(snapshot.source.locks_verified, "Player locks have not been verified.")
        if action == "set_lineup":
            lineup = payload["lineup"]
            slots = snapshot.rules.lineup_slots()
            require(set(lineup) == set(slots), "The proposed lineup must fill every starter slot.")
            require(len(set(lineup.values())) == len(lineup), "A player cannot fill two slots.")
            require(set(lineup.values()) <= set(team.roster_ids), "Lineup players must be on the active roster.")
            current_slots = {pid: slot for slot, pid in team.lineup.items() if pid}
            proposed_slots = {pid: slot for slot, pid in lineup.items()}
            for pid in team.roster_ids:
                if players[pid].locked:
                    require(current_slots.get(pid) == proposed_slots.get(pid), "A locked player cannot change slots.")
            for slot, pid in lineup.items():
                require(bool(set(players[pid].eligible_positions).intersection(slots[slot])), "A player is in an ineligible slot.")
                if not players[pid].locked:
                    require(players[pid].availability in {"ACTIVE", "HEALTHY", "QUESTIONABLE"}
                            and players[pid].bye != snapshot.week, "A proposed starter is not available this week.")
            current = [pid for pid in team.lineup.values() if pid]
            require(all(players[pid].weekly_projection is not None for pid in set(current) | set(lineup.values())),
                    "Weekly projections are required to check the improvement limit.")
            improvement = sum(players[pid].weekly_projection for pid in lineup.values()) - sum(players[pid].weekly_projection for pid in current)
            require(improvement + 1e-8 >= limits.min_lineup_improvement, "The lineup improvement is below the user limit.")
        elif action == "drop_player":
            drop_check(payload["player_id"])
        else:
            pid = payload["player_id"]
            require(pid in players, "Unknown player.")
            require(pid not in {p for t in snapshot.teams for p in t.roster_ids + t.reserve_ids}, "The player is already owned.")
            require(not players[pid].locked, "A locked player cannot be added.")
            require(players[pid].availability in {"ACTIVE", "HEALTHY", "QUESTIONABLE"},
                    "The acquisition player is not confirmed available.")
            if payload.get("drop_id"):
                drop_check(payload["drop_id"])
            roster = [p for p in team.roster_ids if p != payload.get("drop_id")] + [pid]
            require(len(roster) <= snapshot.rules.rounds, "A full active roster requires an allowed drop.")
            require(Counter(players[p].position for p in roster)[players[pid].position] <= snapshot.rules.caps.get(players[pid].position, 0),
                    "The add exceeds the position cap.")
            from .season import _lineup
            baseline = _lineup(snapshot, config, team, allow_empty=True)
            after = _lineup(snapshot, config, team, roster)
            require(not baseline["missing_projections"] and baseline["projected_points"] is not None and after["status"] == "ok",
                    "Complete weekly projections and a legal resulting lineup are required for acquisitions.")
            require(after["projected_points"] - baseline["projected_points"] + 1e-8 >= limits.min_lineup_improvement,
                    "The acquisition lineup improvement is below the user limit.")
            bid = payload["bid"]
            require(action != "free_agent_add" or bid == 0, "Free agent adds must use a zero bid.")
            budget = snapshot.budget
            require(budget is not None and budget.pending_amount is not None and budget.pending_moves is not None,
                    "Budget and pending commitments must be known.")
            require(bid <= limits.faab_per_claim, "The bid exceeds the per-claim limit.")
            require(budget.spent_week + budget.pending_amount + bid <= limits.faab_per_week, "The bid exceeds the weekly FAAB limit.")
            require(budget.spent_season + budget.pending_amount + bid <= limits.faab_per_season, "The bid exceeds the season FAAB limit.")
            require(budget.balance - budget.pending_amount - bid >= limits.faab_reserve, "The bid would spend the FAAB reserve.")
        if action in {"waiver_claim", "free_agent_add", "drop_player"}:
            budget = snapshot.budget
            require(budget is not None and budget.pending_moves is not None, "Pending roster moves must be known.")
            require(budget.roster_moves_week + budget.pending_moves + 1 <= limits.max_weekly_moves, "The weekly roster move limit is reached.")
    return {"mode": mode, "payload": payload, "requires_confirmation": mode == "review", "scope": execution_scope}


def apply_demo_action(snapshot: LeagueSnapshot, action: str, payload: dict) -> LeagueSnapshot:
    """Apply an already checked action. The manager commits this atomically."""
    updated = snapshot.model_copy(deep=True)
    team = updated.own_team()
    if action == "draft_pick":
        team.roster_ids.append(payload["player_id"])
        updated.picks.append(Pick(pick_no=len(updated.picks) + 1, player_id=payload["player_id"], slot=team.slot))
    elif action == "set_lineup":
        team.lineup = payload["lineup"]
    else:
        drop = payload["player_id"] if action == "drop_player" else payload.get("drop_id")
        if drop:
            team.roster_ids.remove(drop)
            team.lineup = {slot: pid if pid != drop else None for slot, pid in team.lineup.items()}
        if action != "drop_player":
            team.roster_ids.append(payload["player_id"])
            updated.budget.balance -= payload["bid"]
            updated.budget.spent_week += payload["bid"]
            updated.budget.spent_season += payload["bid"]
        updated.budget.roster_moves_week += 1
    updated.source.observed_at = datetime.now(timezone.utc)
    return LeagueSnapshot.model_validate(updated.model_dump())
