"""Normalize scoped ESPN HTTP observations without browser evidence.

The public serialization and read contracts are recorded in
``docs/ESPN_HTTP_COMPATIBILITY.md``. This module makes no network requests.
"""

from __future__ import annotations

from copy import deepcopy
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from .espn_data import (ESPNDataError, _array, _integer, _numeric_id, _object,
                        _rules, _scope, _scoring, _verify_player_response_scope)
from .espn_http_client import READ_ORIGIN, league_url
from .espn_season_data import _player, _pool_and_rosters, _week, season_player_read_url
from .models import Budget, ESPNHTTPObservation, ESPNPlayerState, LeagueSnapshot, Source, Team


_LEAGUE_VIEWS = {"mRoster", "mSettings", "mTeam", "mStatus", "mDraftDetail", "mPendingTransactions"}


def season_pro_teams_read_url(season):
    """Return the exact public football season schedule request."""
    _, season = _scope("1", season)
    return f"{READ_ORIGIN}/apis/v3/games/ffl/seasons/{season}?view=proTeamSchedules_wl"


def _pro_team_byes(payload, response_url, season):
    if response_url is not None and response_url != season_pro_teams_read_url(season):
        raise ESPNDataError("The professional team response requires its exact football season URL.")
    if payload is None or response_url is None:
        return None
    _object(payload, "Professional team response")
    for field, expected in (("seasonId", season), ("gameId", 1), ("segmentId", 0)):
        if field in payload and (type(payload[field]) is not int or payload[field] != expected):
            raise ESPNDataError("The professional team response identifies a different scoring context.")
    settings = _object(payload.get("settings"), "Professional team settings")
    result = {}
    for row in _array(settings.get("proTeams"), "Professional teams"):
        row = _object(row, "Professional team")
        identifier, bye = row.get("id"), row.get("byeWeek")
        if type(identifier) is not int or identifier < 0 or identifier in result:
            raise ESPNDataError("A professional team identifier is invalid or duplicated.")
        if type(bye) is not int or not 0 <= bye <= 18 or identifier == 0 and bye != 0:
            raise ESPNDataError("A professional team bye week is invalid.")
        result[identifier] = bye or None
    return result


def _player_bye(raw, state_raw, byes):
    if byes is None:
        return None, None
    raw_id, state_id = raw.get("proTeamId"), state_raw.get("proTeamId")
    for identifier in (raw_id, state_id):
        if identifier is not None and (type(identifier) is not int or identifier < 0):
            raise ESPNDataError("A player's professional team identifier is invalid.")
    if raw_id is not None and state_id is not None and raw_id != state_id:
        raise ESPNDataError("A player's professional team changed between observed responses.")
    identifier = state_id if state_id is not None else raw_id
    if identifier is None:
        return None, None
    if identifier not in byes:
        raise ESPNDataError("A player's professional team has no matching bye-week evidence.")
    return byes[identifier], True


def _boolean(value, field):
    if value is not None and type(value) is not bool:
        raise ESPNDataError(f"{field} must be a boolean or unknown.")
    return value


def _optional_count(value, field, *, minimum=0):
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return _integer(value, field, minimum=minimum)


def _acquisition_counts(league, team, week):
    counter = _object(team.get("transactionCounter", {}), "Team transaction counters")
    season_count = _optional_count(counter.get("acquisitions"), "Completed season acquisitions")
    schedule = _object(league["settings"].get("scheduleSettings", {}), "Schedule settings")
    periods = schedule.get("matchupPeriods")
    current = league["status"].get("currentMatchupPeriod")
    totals = counter.get("matchupAcquisitionTotals")
    if not isinstance(periods, dict) or current is None or not isinstance(totals, dict):
        return season_count, None
    current = _integer(current, "Current matchup period", minimum=1)
    matching = []
    for matchup, scoring_periods in periods.items():
        matchup = _integer(matchup, "Matchup period", minimum=1)
        scoring_periods = [_week(value) for value in _array(scoring_periods, "Matchup scoring periods")]
        if week in scoring_periods:
            matching.append(matchup)
    if matching != [current]:
        return season_count, None
    period_count = _optional_count(totals.get(str(current)), "Completed matchup acquisitions")
    if period_count is not None and season_count is not None and period_count > season_count:
        raise ESPNDataError("Matchup acquisitions exceed the completed season total.")
    return season_count, period_count


def _member(value):
    if not isinstance(value, str):
        raise ESPNDataError("The authenticated member and team owners must have valid member identifiers.")
    try:
        return UUID(value)
    except ValueError:
        raise ESPNDataError("The authenticated member and team owners must have valid member identifiers.") from None


def _response_scope(payload, league, season, week, label):
    _object(payload, label)
    if "id" in payload and _numeric_id(payload["id"], f"{label} league ID") != league:
        raise ESPNDataError(f"{label} identifies a different league.")
    if "seasonId" in payload and _scope(league, payload["seasonId"])[1] != season:
        raise ESPNDataError(f"{label} identifies a different season.")
    if _week(payload.get("scoringPeriodId")) != week:
        raise ESPNDataError(f"{label} identifies a different scoring week.")
    if (_integer(payload.get("gameId", 1), f"{label} game") != 1
            or _integer(payload.get("segmentId", 0), f"{label} segment") != 0):
        raise ESPNDataError(f"{label} is not a supported football league segment.")


def _request_query(url, league, season, label):
    if not isinstance(url, str):
        raise ESPNDataError(f"{label} requires its verified response URL.")
    parsed = urlsplit(url)
    if url.split("?", 1)[0] != league_url(league, season) or parsed.fragment:
        raise ESPNDataError(f"{label} URL identifies a different league or season.")
    return parse_qs(parsed.query, keep_blank_values=True)


def _entries(team):
    entries = _array(_object(team.get("roster"), "Team roster").get("entries"), "Roster entries")
    result = {}
    for entry in entries:
        entry = _object(entry, "Roster entry")
        pid = _numeric_id(entry.get("playerId"), "Roster player ID", player=True)
        if pid in result:
            raise ESPNDataError("A team roster contains duplicate player identifiers.")
        result[pid] = entry
    return result


def _pending_transactions(league, target, known):
    pending = []
    seen = set()
    for transaction in _array(league.get("pendingTransactions", []), "Pending transactions"):
        transaction = _object(transaction, "Pending transaction")
        items = _array(transaction.get("items", []), "Pending transaction items")
        for item in items:
            _object(item, "Pending transaction item")
        if (str(transaction.get("teamId")) != target
                and not any(str(item.get(key)) == target for item in items for key in ("fromTeamId", "toTeamId"))):
            continue
        identifier = transaction.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in seen:
            raise ESPNDataError("A selected-team pending transaction has a missing or duplicate identifier.")
        seen.add(identifier)
        # Preserve action evidence without account member IDs or free-form comments.
        fields = ("id", "type", "teamId", "status", "executionType", "isPending", "scoringPeriodId",
                  "proposedDate", "processDate", "bidAmount", "relatedTransactionId", "subOrder")
        row = {key: deepcopy(transaction[key]) for key in fields if key in transaction}
        row["items"] = [{key: deepcopy(item[key]) for key in
                         ("playerId", "type", "fromTeamId", "toTeamId", "fromLineupSlotId", "toLineupSlotId")
                         if key in item} for item in items]
        pending.append(row)
    return pending, known


def _player_state(wrapper, raw, pending):
    identifiers = []
    for record in (wrapper, raw):
        for value in _array(record.get("pendingTransactionIds", []), "Player pending transaction identifiers"):
            if not isinstance(value, str) or not value:
                raise ESPNDataError("A player pending transaction identifier is invalid.")
            if value not in identifiers:
                identifiers.append(value)
    pid = str(raw["id"])
    for transaction in pending:
        if any(str(item.get("playerId")) == pid for item in transaction["items"]):
            if transaction["id"] not in identifiers:
                identifiers.append(transaction["id"])
    eligible = [_integer(slot, "Player eligible slot")
                for slot in _array(raw.get("eligibleSlots"), "Player eligible slots")]
    status = wrapper.get("status")
    if status is not None and (not isinstance(status, str) or not status):
        raise ESPNDataError("A player acquisition status is invalid.")
    waiver_date = wrapper.get("waiverProcessDate")
    if waiver_date is not None:
        waiver_date = _integer(waiver_date, "Waiver processing date")
    return ESPNPlayerState(
        roster_locked=_boolean(wrapper.get("rosterLocked"), "Player roster lock"),
        trade_locked=_boolean(wrapper.get("tradeLocked"), "Player trade lock"),
        droppable=_boolean(raw.get("droppable"), "Player drop eligibility"),
        injured=_boolean(raw.get("injured"), "Player IR eligibility"),
        eligible_slots=eligible, acquisition_status=status, waiver_process_date=waiver_date,
        pending_transaction_ids=identifiers)


def _budget(league, team, pending, pending_known, uses_faab, notes):
    settings = league["settings"].get("acquisitionSettings")
    counter = team.get("transactionCounter")
    if not isinstance(settings, dict) or not isinstance(counter, dict) or uses_faab is None:
        notes.append("Acquisition settings or completed counters are missing. The budget is unknown.")
        return None
    if any(counter.get(key) is None for key in ("acquisitionBudgetSpent", "acquisitions")):
        notes.append("Completed acquisition counters are incomplete. The budget is unknown.")
        return None
    total = settings.get("acquisitionBudget") if uses_faab else 0
    if total is None:
        notes.append("The acquisition budget is missing.")
        return None
    total = _integer(total, "League acquisition budget")
    spent = _integer(counter["acquisitionBudgetSpent"], "Completed acquisition spending")
    moves = _integer(counter["acquisitions"], "Completed acquisitions")
    if uses_faab and spent > total:
        raise ESPNDataError("Acquisition spending exceeds the league budget.")
    if spent or moves:
        notes.append("Nonzero completed counters require weekly transaction history. The budget is unknown.")
        return None
    amount = count = 0
    if not pending_known:
        amount = count = None
    else:
        for transaction in pending:
            if transaction.get("type") not in {"WAIVER", "FREEAGENT"}:
                continue
            additions = [item for item in transaction["items"] if item.get("type") == "ADD"
                         and str(item.get("toTeamId")) == str(team["id"])]
            if not additions:
                notes.append("A pending acquisition has incomplete items. Its budget reservation is unknown.")
                amount = count = None
                break
            count += len(additions)
            if uses_faab:
                if transaction.get("bidAmount") is None:
                    amount = None
                elif amount is not None:
                    amount += _integer(transaction["bidAmount"], "Pending acquisition bid")
    return Budget(balance=total, spent_week=0, spent_season=0, roster_moves_week=0,
                  pending_amount=amount, pending_moves=count)


def normalize_espn_http(league_payload, players_payload, roster_payload, *, team_id, week, member_id,
                        observed_at, projections_observed_at=None, player_response_url=None,
                        roster_response_url=None, league_response_url=None,
                        pro_teams_payload=None, pro_teams_response_url=None) -> LeagueSnapshot:
    """Build a season snapshot from authenticated, scoped HTTP responses.

    The adapter must reject redirects and pass each response URL unchanged.
    Targeted roster locks replace general pool defaults. Missing flags remain unknown.
    A missing league URL cannot establish that pending transactions were requested.
    Missing professional team scope leaves bye-week evidence unknown.
    """
    target, week = _numeric_id(team_id, "Requested team ID"), _week(week)
    _object(league_payload, "League payload")
    league, season = _scope(league_payload.get("id"), league_payload.get("seasonId"))
    byes = _pro_team_byes(pro_teams_payload, pro_teams_response_url, season)
    _response_scope(league_payload, league, season, week, "League response")
    _response_scope(roster_payload, league, season, week, "Targeted roster response")
    expected_pool = season_player_read_url(league, season, week)
    if player_response_url != expected_pool:
        raise ESPNDataError("The player pool requires its exact verified response URL.")
    _verify_player_response_scope(players_payload, league, season, expected_pool, player_response_url)
    if "scoringPeriodId" in players_payload and _week(players_payload["scoringPeriodId"]) != week:
        raise ESPNDataError("The player response identifies a different scoring week.")
    query = _request_query(roster_response_url, league, season, "Targeted roster response")
    if query != {"forTeamId": [target], "scoringPeriodId": [str(week)], "view": ["mRoster"]}:
        raise ESPNDataError("Lock evidence requires the exact selected-team roster request.")
    pending_known = False
    if league_response_url is not None:
        query = _request_query(league_response_url, league, season, "League response")
        if (set(query) - {"view", "scoringPeriodId", "rosterForTeamId"}
                or query.get("scoringPeriodId") != [str(week)]
                or "rosterForTeamId" in query and query["rosterForTeamId"] != [target]):
            raise ESPNDataError("The league response URL does not match the requested scoring context.")
        if not _LEAGUE_VIEWS.issubset(query.get("view", [])):
            raise ESPNDataError("The league response URL does not include every required view.")
        pending_known = True
    if _object(league_payload.get("draftDetail"), "Draft detail").get("drafted") is not True:
        raise ESPNDataError("A completed draft must be verified before season normalization.")
    rules, order, names, _ = _rules(league_payload, target)
    target_team = next(team for team in league_payload["teams"] if str(team["id"]) == target)
    owners = {_member(owner) for owner in _array(target_team.get("owners"), "Selected-team owners")}
    if _member(member_id) not in owners:
        raise ESPNDataError("The authenticated member does not own the selected team.")
    if target_team.get("primaryOwner") is not None and _member(target_team["primaryOwner"]) not in owners:
        raise ESPNDataError("The selected team's primary owner conflicts with its owner list.")
    scoped_teams = _array(roster_payload.get("teams"), "Targeted roster teams")
    if len(scoped_teams) != 1 or _numeric_id(_object(scoped_teams[0], "Targeted team").get("id"), "Targeted team ID") != target:
        raise ESPNDataError("The targeted roster response must contain only the selected team.")
    broad_entries, own_entries = _entries(target_team), _entries(scoped_teams[0])
    if set(broad_entries) != set(own_entries):
        raise ESPNDataError("Selected-team ownership changed between the league and targeted roster responses.")
    for pid, entry in own_entries.items():
        if entry.get("lineupSlotId") != broad_entries[pid].get("lineupSlotId"):
            raise ESPNDataError("The selected lineup changed between the league and targeted roster responses.")
        wrapper = _object(entry.get("playerPoolEntry"), "Targeted player pool entry")
        if _numeric_id(wrapper.get("onTeamId"), "Targeted player owner") != target:
            raise ESPNDataError("A targeted player's owner conflicts with the selected team.")
        raw = _object(wrapper.get("player"), "Targeted player")
        if _numeric_id(raw.get("id"), "Targeted player ID", player=True) != pid:
            raise ESPNDataError("A targeted player identifier conflicts with its roster entry.")
    merged = deepcopy(league_payload)
    next(team for team in merged["teams"] if str(team["id"]) == target)["roster"] = deepcopy(scoped_teams[0]["roster"])
    raw_players, rosters, ownership = _pool_and_rosters(merged, players_payload, order, rules)
    pool = {}
    for wrapper in players_payload["players"]:
        raw = wrapper.get("player", wrapper)
        pid = _numeric_id(raw.get("id"), "Pool player ID", player=True)
        pool[pid] = wrapper
        if wrapper.get("onTeamId") is not None:
            owner = _integer(wrapper["onTeamId"], "Pool player owner")
            if owner != int(ownership.get(pid, 0)):
                raise ESPNDataError("Player-pool ownership conflicts with the current complete rosters.")
    pending, pending_known = _pending_transactions(league_payload, target, pending_known)
    notes = ["HTTP lock evidence comes from the exact selected-team roster request.",
             "Projection timestamps record downloads, not ESPN publication times.",
             "Missing weekly projections remain null. Injury status text does not establish IR eligibility."]
    if not pending_known:
        notes.append("The pending-transaction request scope is unknown.")
    settings = league_payload["settings"]
    acquisition = _object(settings.get("acquisitionSettings", {}), "Acquisition settings")
    uses_faab = _boolean(acquisition.get("isUsingAcquisitionBudget"), "FAAB setting")
    team_locked = _boolean(target_team.get("isTransactionLocked"), "Team transaction lock")
    status = _object(league_payload.get("status"), "League status")
    latest = _week(status.get("latestScoringPeriod"))
    transaction_period = _week(status.get("transactionScoringPeriod"))
    final = _week(status.get("finalScoringPeriod"))
    if week > final or latest > final or transaction_period > final:
        raise ESPNDataError("The requested scoring context is outside the active season.")
    locks = {pid: _boolean(entry["playerPoolEntry"].get("lineupLocked"), "Targeted lineup lock")
             for pid, entry in own_entries.items()}
    locks_verified = bool(own_entries) and all(value is not None for value in locks.values())
    players, omitted = [], 0
    scoring = _scoring(league_payload)
    for pid, raw in raw_players.items():
        wrapper = own_entries[pid]["playerPoolEntry"] if pid in own_entries else pool.get(pid, {})
        state_raw = wrapper.get("player", raw)
        player = _player(raw, season, week, scoring)
        if player is None:
            if pid in ownership:
                raise ESPNDataError("A rostered player has an unsupported position.")
            omitted += 1
            continue
        player.espn = _player_state(wrapper, state_raw, pending)
        pool_raw = pool.get(pid, {}).get("player", raw)
        player.bye, player.espn.bye_verified = _player_bye(pool_raw, state_raw, byes)
        if pid in own_entries:
            player.locked = locks[pid] is not False
        elif (pid not in ownership and wrapper.get("onTeamId") in (0, "0") and locks_verified
              and team_locked is False and player.espn.acquisition_status in {"FREEAGENT", "WAIVERS"}
              and player.espn.roster_locked is not None and player.espn.trade_locked is not None):
            player.locked = (_boolean(wrapper.get("lineupLocked"), "Pool lineup lock") is not False
                             or player.espn.roster_locked is not False or player.espn.trade_locked is not False)
        players.append(player)
    notes.extend([f"Weekly projections are missing for {sum(p.weekly_projection is None for p in players)} supported players.",
                  f"Bye-week evidence is unknown for {sum(p.espn.bye_verified is not True for p in players)} supported players.",
                  f"Excluded {omitted} unsupported player rows."])
    if byes is not None:
        notes.append(f"Bye-week evidence uses the verified season response: {pro_teams_response_url}")
    minimum_bid = acquisition.get("minimumBid")
    if minimum_bid is not None:
        minimum_bid = _integer(minimum_bid, "Minimum acquisition bid")
    acquisition_type = acquisition.get("acquisitionType")
    if acquisition_type is not None and (not isinstance(acquisition_type, str) or not acquisition_type):
        raise ESPNDataError("The league acquisition type is invalid.")
    season_acquisitions, period_acquisitions = _acquisition_counts(league_payload, target_team, week)
    budget = _budget(league_payload, target_team, pending, pending_known, uses_faab, notes)
    source = Source(provider="espn_http", observed_at=observed_at,
                    projections_observed_at=projections_observed_at or observed_at,
                    complete=True, synthetic=False, locks_verified=locks_verified,
                    locks_scope="selected_team", notes=notes,
                    http=ESPNHTTPObservation(league_id=league, team_id=target, season=season, week=week,
                         roster_url=roster_response_url, ownership_verified=True, transaction_period=transaction_period,
                         latest_period=latest, final_period=final, team_transaction_locked=team_locked,
                         pending_transactions_known=pending_known, pending_transactions=pending,
                         uses_faab=uses_faab, acquisition_type=acquisition_type, minimum_bid=minimum_bid,
                         acquisition_limit=_optional_count(acquisition.get("acquisitionLimit"),
                                                           "Season acquisition limit", minimum=-1),
                         matchup_acquisition_limit=_optional_count(acquisition.get("matchupAcquisitionLimit"),
                                                                   "Matchup acquisition limit", minimum=-1),
                         acquisitions_season=season_acquisitions, acquisitions_period=period_acquisitions,
                         uses_undroppable_list=_boolean(settings["rosterSettings"].get("isUsingUndroppableList"),
                                                        "Undroppable-list setting")))
    if source.projections_observed_at > source.observed_at:
        raise ESPNDataError("The projection download time is later than the roster observation.")
    return LeagueSnapshot(league_id=league, team_id=target, season=season, week=week, phase="season",
                          source=source, rules=rules, players=players,
                          budget=budget,
                          teams=[Team(id=tid, name=names[tid], slot=slot, roster_ids=rosters[tid][0],
                                      reserve_ids=rosters[tid][1], lineup=rosters[tid][2])
                                 for slot, tid in enumerate(order, 1)])
