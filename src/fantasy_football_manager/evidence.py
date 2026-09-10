"""Allowlisted local evidence. Remote delivery is outside manager transactions."""

import hashlib
import json
import math
from datetime import datetime, timezone

from . import __version__


def initialize(db):
    db.execute("CREATE TABLE IF NOT EXISTS ffm_archive_outbox "
               "(id INTEGER PRIMARY KEY, at TEXT NOT NULL, event TEXT NOT NULL, detail TEXT NOT NULL)")


def append(db, event, detail):
    db.execute("INSERT INTO ffm_archive_outbox(at,event,detail) VALUES(?,?,?)",
               (datetime.now(timezone.utc).isoformat(), event,
                json.dumps(detail, sort_keys=True, separators=(",", ":"), allow_nan=False)))


def semantic_snapshot(snapshot):
    value = snapshot.model_dump(mode="json")
    value["source"].pop("observed_at", None)
    value["source"].pop("projections_observed_at", None)
    value["players"].sort(key=lambda item: item["id"])
    value["teams"].sort(key=lambda item: item["id"])
    return value


def fingerprint(snapshot, config=None):
    value = {"snapshot": semantic_snapshot(snapshot)} if snapshot is not None else {"snapshot": None}
    if config is not None:
        value["config"] = config.model_dump(mode="json")
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


def _fields(value, keys):
    return {key: value[key] for key in keys if key in value}


def transaction_record(value):
    """Retain transaction identifiers and state. Omit account data and free-form server fields."""
    scalar_keys = {"id", "type", "teamId", "scoringPeriodId", "status", "isPending", "bidAmount", "executionType"}
    item_keys = {"playerId", "type", "fromTeamId", "toTeamId", "fromLineupSlotId", "toLineupSlotId"}

    def scalars(row, keys):
        return {key: item[:160] if isinstance(item, str) else item for key, item in row.items()
                if key in keys and (item is None or type(item) in {str, int, bool})}

    result = scalars(value, scalar_keys)
    if isinstance(value.get("items"), list):
        result["items"] = [scalars(item, item_keys) for item in value["items"] if isinstance(item, dict)]
    return result


def http_record(value):
    result = _fields(value, ("league_id", "team_id", "season", "week", "ownership_verified", "transaction_period",
                            "latest_period", "final_period", "team_transaction_locked", "pending_transactions_known",
                            "uses_faab", "acquisition_type", "minimum_bid", "acquisition_limit",
                            "matchup_acquisition_limit", "acquisitions_season", "acquisitions_period", "uses_undroppable_list"))
    for key in ("pending_transactions", "recent_transactions"):
        if isinstance(value.get(key), list):
            result[key] = [transaction_record(item) for item in value[key] if isinstance(item, dict)]
    return result


def snapshot_record(snapshot):
    """Retain typed decision inputs. Omit navigation URLs, notes, and display names."""
    value = snapshot.model_dump(mode="json")
    result = _fields(value, ("schema_version", "league_id", "team_id", "season", "phase", "week", "rules", "budget", "picks"))
    result["teams"] = [_fields(team, ("id", "slot", "roster_ids", "reserve_ids", "lineup")) for team in value["teams"]]
    result["players"] = [_fields(player, ("id", "position", "eligible_positions", "projection", "weekly_projection",
        "weekly_floor", "weekly_ceiling", "adp", "availability", "locked", "bye")) for player in value["players"]]
    for player, record in zip(value["players"], result["players"]):
        if player.get("espn"):
            record["espn"] = _fields(player["espn"], ("roster_locked", "trade_locked", "droppable", "injured", "bye_verified",
                                                       "eligible_slots", "acquisition_status", "waiver_process_date",
                                                       "pending_transaction_ids"))
    result["source"] = _fields(value["source"], ("provider", "observed_at", "projections_observed_at", "complete",
                                                  "locks_verified", "locks_scope", "synthetic"))
    browser = value["source"].get("browser")
    if browser:
        result["source"]["browser"] = _fields(browser, ("league_id", "team_id", "current_pick", "autopick_enabled", "draft_complete"))
    if value["source"].get("http"):
        result["source"]["http"] = http_record(value["source"]["http"])
    return result


def envelope(snapshot, config, revision, config_revision, *, include_snapshot=False):
    context = {"revision": revision, "config_revision": config_revision}
    if snapshot is not None:
        context.update({key: getattr(snapshot, key) for key in ("league_id", "team_id", "season", "phase", "week")})
    result = {"schema_version": 1, "application_version": __version__, "context": context,
              "input_fingerprint": fingerprint(snapshot, config), "config": config.model_dump(mode="json")}
    if snapshot is not None:
        result["source"] = snapshot_record(snapshot)["source"]
        if include_snapshot:
            result["snapshot"] = snapshot_record(snapshot)
    return result


_SCALARS = frozenset({
    "id", "player_id", "add_player_id", "drop_player_id", "drop_id", "repair_player_id", "outgoing_player_id", "proposal_id", "team_id", "bid",
    "action", "scope", "executor", "status", "position", "source_slot", "destination_slot", "slot", "pick_no",
    "authorized_at", "observed_at", "revision", "config_revision", "mode", "requires_confirmation", "should_click",
    "retry_allowed", "idempotent_replay", "clicked", "uncertain", "model_version", "strategy", "phase", "completed", "draft_complete",
    "current_pick", "my_next_pick", "following_pick", "available_count", "trials", "requested_trials", "seed",
    "snapshot_age_seconds", "source_observed_at", "snapshot_complete", "stale", "projections_observed_at",
    "projection_age_seconds", "analysis_fingerprint", "automation_paused", "action_mode", "projection", "adp",
    "score", "score_se", "score_sum", "score_sq_sum", "simulation_count", "availability_count", "survival_count",
    "trial_count", "availability_at_pick", "survival_next_pick", "adp_reach", "estimate_quality", "week",
    "projected_points", "current_points", "current_projected_points", "improvement", "objective", "objective_value",
    "weekly_projection", "weekly_floor", "weekly_ceiling", "weekly_upside_gain", "maximum_faab_bid", "rank",
    "baseline_projected_points", "bid_win_probability", "platform_claim_status_verified", "championship_odds", "basis",
    "comparison_complete", "projection_complete", "comparison_scope", "objective_field", "objective_points",
    "should_submit", "authorized", "source_ready", "platform_eligibility_verified", "remaining_weekly_moves",
    "availability", "locked", "provider", "complete", "locks_verified", "locks_scope", "synthetic",
})
_OBJECTS = frozenset({"payload", "actual_pick", "result", "source", "effective_limits", "coverage"})
_LISTS = frozenset({"recommendations", "candidates", "rankings", "blocked_candidates", "missing_projections",
                    "blocking_missing_projections", "excluded_players", "gaps"})
_ID_MAPS = frozenset({"lineup", "actual_lineup", "fixed_slots"})
_ID_LISTS = frozenset({"backup_player_ids", "actual_roster_ids", "actual_reserve_ids"})
_REASON_CODES = frozenset({"vacant_slot", "starter_unavailable", "starter_availability_risk", "starter_projection_unknown",
                          "no_projected_bench_cover", "source_not_ready", "budget_unknown", "weekly_move_limit",
                          "platform_acquisition_eligibility_unverified", "coverage_repair_not_enabled", "other_vacant_slots",
                          "locked_bench", "unavailable_this_week"})
_PROJECTION_FIELDS = frozenset({"weekly_projection", "weekly_floor", "weekly_ceiling"})
_SUBMISSION_PHASES = frozenset({"preflight", "request", "response", "reconciliation"})
_ERROR_CATEGORIES = frozenset({"authentication", "rate_limited", "timeout", "history_gap", "stale_source",
                             "scope_mismatch", "profile_busy", "browser_control", "policy_blocked", "unclassified"})


def action_or_result(value):
    """Drop free-form messages and unknown fields before writing the outbox."""
    result = {}
    for key, item in value.items():
        if key in _SCALARS and (item is None or type(item) in {str, int, float, bool}):
            if isinstance(item, float) and not math.isfinite(item):
                continue
            result[key] = item[:160] if isinstance(item, str) else item
        elif key in _OBJECTS and isinstance(item, dict):
            result[key] = action_or_result(item)
        elif key in _LISTS and isinstance(item, list):
            result[key] = [action_or_result(row) for row in item if isinstance(row, dict)]
        elif key in _ID_LISTS and isinstance(item, list):
            result[key] = [pid[:160] for pid in item if isinstance(pid, str)]
        elif key in {"reasons", "blocking_reasons", "fields"} and isinstance(item, list):
            allowed = _PROJECTION_FIELDS if key == "fields" else _REASON_CODES
            result[key] = [code for code in item if isinstance(code, str) and code in allowed]
        elif key == "reason" and isinstance(item, str) and item in _REASON_CODES:
            result[key] = item
        elif key == "transaction" and isinstance(item, dict):
            result[key] = transaction_record(item)
        elif key == "http" and isinstance(item, dict):
            result[key] = http_record(item)
        elif key == "submission_phase" and isinstance(item, str) and item in _SUBMISSION_PHASES:
            result[key] = item
        elif key == "error_category" and (item is None or isinstance(item, str) and item in _ERROR_CATEGORIES):
            result[key] = item
        elif key == "error":
            result["error_category"] = failure_category(item)
        elif key in {"unfilled_slots", "baseline_unfilled_slots"} and isinstance(item, list):
            result[key] = [slot for slot in item if isinstance(slot, str)
                           and slot.rstrip("0123456789") in {"QB", "RB", "WR", "TE", "DST", "K", "FLEX"}]
        elif key in _ID_MAPS and isinstance(item, dict):
            result[key] = {str(slot): pid for slot, pid in item.items()
                           if (pid is None or isinstance(pid, str)) and str(slot).rstrip("0123456789") in {"QB", "RB", "WR", "TE", "DST", "K", "FLEX"}}
    return result


def failure_category(message):
    """Classify an observed message. This category does not establish root cause."""
    message = str(message or "").lower()
    for category, markers in (
        ("authentication", ("401", "403", "sign in", "login", "unauthorized", "forbidden")),
        ("rate_limited", ("429", "rate limit")),
        ("timeout", ("timeout", "timed out")),
        ("history_gap", ("history", "missing picks", "missing pick")),
        ("stale_source", ("stale", "older observation", "age limit", "predates")),
        ("scope_mismatch", ("another league", "different league", "team ident", "context")),
        ("profile_busy", ("another manager process", "browser profile", "owns the espn browser")),
        ("browser_control", ("autocomplete", "search", "button", "selector", "draft row")),
        ("policy_blocked", ("policy", "limit", "locked", "paused", "confirmation", "autopick")),
    ):
        if any(marker in message for marker in markers):
            return category
    return "unclassified" if message else None


AUDIT_EVENTS = frozenset({"config_updated", "action_prepared", "demo_action_executed",
    "browser_draft_prepared", "browser_draft_authorized", "browser_draft_reconciled",
    "browser_lineup_prepared", "browser_lineup_authorized", "browser_lineup_reconciled",
    "espn_http_prepared", "espn_http_authorized", "espn_http_response", "espn_http_reconciled", "espn_http_not_submitted"})
