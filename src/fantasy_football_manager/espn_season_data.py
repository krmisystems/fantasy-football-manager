"""Normalize read-only ESPN season observations without guessing weekly data.

ESPN's fantasy interface is unofficial. Roster and weekly record shapes also
appear in the maintained espn-api reader:
https://github.com/cwendt94/espn-api/blob/master/espn_api/football/box_player.py
https://github.com/cwendt94/espn-api/blob/master/espn_api/football/team.py
These references do not establish an official ESPN API or write capability.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
import re
from urllib.parse import parse_qs, urlsplit

from .espn_data import (BASE, ESPNDataError, POSITIONS, PRIMARY_SLOTS, SLOTS,
                        _array, _integer, _number, _numeric_id, _object,
                        _page_scope, _rules, _scope, _scoring,
                        _verify_player_response_scope, player_read_headers)
from .models import Budget, LeagueSnapshot, Player, Source, Team


def _week(value):
    value = _integer(value, "Scoring week", minimum=1)
    if value > 18:
        raise ESPNDataError("Scoring week is outside the supported range.")
    return value


def season_read_url(league_id, season, week):
    """Read league rules, every roster, and the requested scoring period."""
    league, year = _scope(league_id, season)
    period = _week(week)
    return (f"{BASE}/seasons/{year}/segments/0/leagues/{league}?view=mSettings&view=mTeam"
            f"&view=mRoster&view=mMatchup&view=mStatus&view=mDraftDetail&scoringPeriodId={period}")


def season_player_read_url(league_id, season, week):
    league, year = _scope(league_id, season)
    period = _week(week)
    return f"{BASE}/seasons/{year}/segments/0/leagues/{league}?view=kona_player_info&scoringPeriodId={period}"


def season_player_read_headers(season=None):
    """Request the player pool without restricting it to free agents."""
    return player_read_headers(season)


def _projection(raw, season, week, scoring):
    records = [record for record in _array(raw.get("stats", []), "Player statistics")
               if isinstance(record, dict) and record.get("seasonId") == season
               and record.get("statSourceId") == 1
               and record.get("statSplitTypeId") == (1 if week else 0)
               and record.get("scoringPeriodId") == week]
    if not records:
        return None
    if len(records) != 1:
        raise ESPNDataError("A player has duplicate projection records for the selected period.")
    stats = _object(records[0].get("stats"), "Projection statistics")
    if not stats:
        return None
    position = str(raw["defaultPositionId"])
    return round(sum(_number(stats.get(stat, 0), "Projected statistic") * overrides.get(position, points)
                     for stat, points, overrides in scoring), 6)


def _player(raw, season, week, scoring):
    pid = _numeric_id(raw.get("id"), "Player ID", player=True)
    position_id = _integer(raw.get("defaultPositionId"), "Player position")
    if position_id not in POSITIONS:
        return None
    eligible = _array(raw.get("eligibleSlots"), "Player eligibility")
    positions = list(dict.fromkeys(PRIMARY_SLOTS[slot] for slot in eligible if slot in PRIMARY_SLOTS))
    if POSITIONS[position_id] not in positions:
        raise ESPNDataError("A player has no verified primary position eligibility.")
    ownership = _object(raw.get("ownership") or {}, "Player ownership")
    adp = _number(ownership.get("averageDraftPosition", 999), "Average draft position")
    status = raw.get("injuryStatus")
    if not status:
        status = "ACTIVE" if raw.get("active") is True else "INACTIVE" if raw.get("active") is False else "UNKNOWN"
    annual = _projection(raw, season, 0, scoring)
    if annual is not None and annual < 0:
        raise ESPNDataError("Negative season totals are not supported by the shared player model.")
    return Player(id=pid, name=raw.get("fullName"), position=POSITIONS[position_id],
                  eligible_positions=positions, team=str(raw.get("proTeamAbbreviation") or raw.get("proTeamId") or ""),
                  projection=annual, weekly_projection=_projection(raw, season, week, scoring),
                  adp=adp if 0 < adp < 999 else 999, availability=status, locked=True)


def _pool_and_rosters(league_payload, players_payload, order, rules):
    raw_players, pool_owners = {}, {}
    for item in _array(players_payload.get("players"), "Player pool"):
        item = _object(item, "Player pool entry")
        raw = _object(item.get("player", item), "Player")
        pid = _numeric_id(raw.get("id"), "Player ID", player=True)
        if pid in raw_players:
            raise ESPNDataError("The player pool contains duplicate identifiers.")
        if "id" in item and _numeric_id(item["id"], "Pool player ID", player=True) != pid:
            raise ESPNDataError("The pool entry and player identifiers conflict.")
        raw_players[pid] = deepcopy(raw)
        if item.get("onTeamId") not in (None, 0, "0"):
            pool_owners[pid] = _numeric_id(item["onTeamId"], "Player owner")
    ownership, rosters = {}, {}
    for raw_team in league_payload["teams"]:
        tid = _numeric_id(raw_team["id"], "Team ID")
        roster = _object(raw_team.get("roster"), "Team roster")
        entries = _array(roster.get("entries"), "Roster entries")
        active, reserve, lineup = [], [], {slot: None for slot in rules.lineup_slots()}
        counts = Counter()
        for entry in entries:
            entry = _object(entry, "Roster entry")
            pid = _numeric_id(entry.get("playerId"), "Roster player ID", player=True)
            if pid in ownership:
                raise ESPNDataError("Roster ownership contains a duplicate player.")
            ownership[pid] = tid
            slot_id = _integer(entry.get("lineupSlotId"), "Roster lineup slot")
            if slot_id not in SLOTS:
                raise ESPNDataError("A roster uses an unsupported lineup slot.")
            embedded = entry.get("playerPoolEntry")
            if embedded is not None:
                embedded = _object(embedded, "Roster player pool entry")
                raw = _object(embedded.get("player"), "Roster player")
                if _numeric_id(raw.get("id"), "Embedded player ID", player=True) != pid:
                    raise ESPNDataError("The roster and embedded player identifiers conflict.")
                if embedded.get("onTeamId") not in (None, 0, "0", int(tid), tid):
                    raise ESPNDataError("The embedded player owner conflicts with the team roster.")
                if pid not in raw_players:
                    raw_players[pid] = deepcopy(raw)
                else:
                    # Roster metadata is the fresher response. Cached projection
                    # statistics retain their separate download timestamp.
                    for key in ("fullName", "defaultPositionId"):
                        if raw.get(key) is not None and raw_players[pid].get(key) != raw[key]:
                            raise ESPNDataError("Roster and player-pool identity fields conflict.")
                    for key in ("eligibleSlots", "active", "injuryStatus", "proTeamId", "proTeamAbbreviation"):
                        if key in raw:
                            raw_players[pid][key] = deepcopy(raw[key])
            if pid not in raw_players:
                raise ESPNDataError("A rostered player has no player metadata.")
            position = SLOTS[slot_id]
            if position == "IR":
                reserve.append(pid)
            else:
                active.append(pid)
                if position != "BN":
                    counts[position] += 1
                    slot = f"{position}{counts[position]}"
                    if slot not in lineup:
                        raise ESPNDataError("A roster exceeds the configured starter slots.")
                    lineup[slot] = pid
        rosters[tid] = (active, reserve, lineup)
    if set(rosters) != set(order):
        raise ESPNDataError("The response does not contain every team roster.")
    if any(ownership.get(pid) != tid for pid, tid in pool_owners.items()):
        raise ESPNDataError("Player-pool ownership conflicts with the complete team rosters.")
    return raw_players, rosters, ownership


def _ui_week_verified(page_url, visible_text, week, observed_week):
    query = parse_qs(urlsplit(page_url).query)
    if "scoringPeriodId" in query:
        if query["scoringPeriodId"] != [str(week)]:
            raise ESPNDataError("The visible page identifies a different scoring week.")
        return True
    if observed_week is not None:
        if _week(observed_week) != week:
            raise ESPNDataError("The verified visible week does not match the requested week.")
        return True
    visible_weeks = {int(value) for value in re.findall(r"\bWEEK\s+(\d{1,2})\b", visible_text, re.I)}
    return visible_weeks == {week}


def _budget(league_payload, target, notes):
    """Retain only counters whose weekly meaning can be established.

    The observed team counter contains season totals. A season total of zero
    proves a zero weekly total. Nonzero totals cannot be assigned to this week.
    Pending claims remain unknown even when all completed counters are zero.
    """
    team = next(t for t in league_payload["teams"] if str(t["id"]) == target)
    settings = league_payload["settings"].get("acquisitionSettings")
    counter = team.get("transactionCounter")
    if not isinstance(settings, dict) or not isinstance(counter, dict):
        notes.append("FAAB and transaction counters are unavailable. The budget is unknown.")
        return None
    required = (settings.get("acquisitionBudget"), counter.get("acquisitionBudgetSpent"), counter.get("acquisitions"))
    if any(value is None for value in required):
        notes.append("The response does not provide every required FAAB and transaction counter.")
        return None
    total = _integer(required[0], "League acquisition budget")
    spent = _integer(required[1], "Season acquisition spending")
    moves = _integer(required[2], "Season acquisitions")
    if spent > total:
        raise ESPNDataError("Season acquisition spending exceeds the reported league budget.")
    if spent or moves:
        notes.append("Season acquisition counters are present, but weekly spending and moves are unknown. The budget remains unset.")
        return None
    notes.append("Zero completed season acquisitions establish zero weekly totals. Pending claims and bids remain unknown.")
    return Budget(balance=total, spent_week=0, spent_season=0, roster_moves_week=0,
                  pending_amount=None, pending_moves=None)


def normalize_espn_season(league_payload, players_payload, *, team_id, week,
                          visible_text, page_url, observed_at, observed_team_id=None,
                          projections_observed_at=None, player_locks=None,
                          observed_week=None, player_response_url=None) -> LeagueSnapshot:
    """Build a season snapshot from complete roster and player responses.

    ``player_locks`` maps verified player IDs to lock booleans. True means locked.
    The browser must verify these states from the correct week's move controls.
    Unknown locks default to True. Selected-team coverage determines locks_verified.
    ``observed_week`` is optional evidence from a verified visible week control.
    ``player_response_url`` identifies the verified request when ESPN omits
    player-response scope fields. The browser must reject response redirects.
    Projection timestamps describe downloads, not ESPN publication times.
    """
    target = _numeric_id(team_id, "Requested team ID")
    week = _week(week)
    league, season, verified_team = _page_scope(page_url, target, observed_team_id)
    if not isinstance(visible_text, str) or not visible_text.strip():
        raise ESPNDataError("The visible team observation is empty.")
    _object(league_payload, "ESPN league payload")
    if _scope(league_payload.get("id"), league_payload.get("seasonId")) != (league, season):
        raise ESPNDataError("The ESPN payload and page identify different league or season scopes.")
    if league_payload.get("gameId", 1) != 1 or league_payload.get("segmentId", 0) != 0:
        raise ESPNDataError("The ESPN payload is not a supported football league segment.")
    _verify_player_response_scope(players_payload, league, season,
                                  season_player_read_url(league, season, week), player_response_url)
    for payload in (league_payload, players_payload):
        if "scoringPeriodId" in payload and _week(payload["scoringPeriodId"]) != week:
            raise ESPNDataError("The ESPN response identifies a different scoring week.")
    if league_payload.get("scoringPeriodId") != week:
        raise ESPNDataError("The roster response must identify the requested scoring week.")
    if league_payload.get("draftDetail", {}).get("drafted") is not True:
        raise ESPNDataError("A completed draft must be verified before season normalization.")
    rules, order, names, _ = _rules(league_payload, target)
    raw_players, rosters, ownership = _pool_and_rosters(league_payload, players_payload, order, rules)
    scoring = _scoring(league_payload)
    players, omitted = [], 0
    for pid, raw in raw_players.items():
        player = _player(raw, season, week, scoring)
        if player is None:
            if pid in ownership:
                raise ESPNDataError("A rostered player has an unsupported position.")
            omitted += 1
            continue
        players.append(player)
    own_ids = set(rosters[target][0] + rosters[target][1])
    verified_week = _ui_week_verified(page_url, visible_text, week, observed_week)
    locks = {} if player_locks is None else _object(player_locks, "Observed player locks")
    known_ids = {p.id for p in players}
    if any(type(value) is not bool for value in locks.values()) or set(locks) - known_ids:
        raise ESPNDataError("Observed locks must reference known player IDs and contain booleans.")
    if locks and not verified_week:
        raise ESPNDataError("Verify the visible scoring week before supplying player locks.")
    for player in players:
        player.locked = locks.get(player.id, True)
    notes = ["Projection timestamps record downloads, not ESPN publication times.",
             "Missing weekly projections remain null. Season totals are never divided into weekly estimates.",
             "Game deadlines and default API lock flags do not establish editable lineup controls.",
             "Locks are verified only for players covered by the supplied UI observations. Unobserved players remain locked.",
             f"Weekly projections are missing for {sum(p.weekly_projection is None for p in players)} supported players.",
             f"Excluded {omitted} unsupported player rows."]
    budget = _budget(league_payload, target, notes)
    source = Source(provider="espn_browser", observed_at=observed_at, synthetic=False, complete=True,
                    projections_observed_at=projections_observed_at or observed_at,
                    locks_verified=bool(own_ids) and verified_week and own_ids.issubset(locks),
                    locks_scope="selected_team", notes=notes,
                    browser={"page_url": page_url, "league_id": league, "team_id": verified_team,
                             "current_pick": None, "autopick_enabled": None, "draft_complete": True})
    if source.projections_observed_at > source.observed_at:
        raise ESPNDataError("The projection download time is later than the team observation.")
    return LeagueSnapshot(league_id=league, team_id=target, season=season, week=week, phase="season", source=source,
                          rules=rules, players=players, budget=budget,
                          teams=[Team(id=tid, name=names[tid], slot=slot, roster_ids=rosters[tid][0],
                                      reserve_ids=rosters[tid][1], lineup=rosters[tid][2])
                                 for slot, tid in enumerate(order, 1)])
