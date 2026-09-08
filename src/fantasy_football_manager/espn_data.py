"""Validate ESPN draft observations from an authenticated browser.

ESPN's fantasy endpoints are unofficial. This module does not fetch data or
submit actions. Projection timestamps record downloads, not publication dates.
Weekly projections and game locks are not inferred from draft data.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from urllib.parse import parse_qs, urlsplit

from .models import LeagueSnapshot, Pick, Player, Rules, Source, Team

BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"
POSITIONS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DST"}
SLOTS = {0: "QB", 2: "RB", 4: "WR", 6: "TE", 16: "DST", 17: "K", 20: "BN", 21: "IR", 23: "FLEX"}
PRIMARY_SLOTS = {0: "QB", 2: "RB", 4: "WR", 6: "TE", 16: "DST", 17: "K"}


class ESPNDataError(ValueError):
    """An ESPN observation is incomplete or inconsistent."""


def _integer(value, field, *, minimum=0):
    if isinstance(value, bool) or not re.fullmatch(r"-?\d+", str(value)):
        raise ESPNDataError(f"{field} must be an integer.")
    number = int(value)
    if number < minimum:
        raise ESPNDataError(f"{field} is outside the supported range.")
    return number


def _numeric_id(value, field, *, player=False):
    number = _integer(value, field, minimum=-999999999 if player else 1)
    if player and number in (-1, 0):
        raise ESPNDataError("A player identifier cannot be a pick placeholder.")
    return str(number)


def _number(value, field):
    if isinstance(value, bool):
        raise ESPNDataError(f"{field} must be a finite number.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ESPNDataError(f"{field} must be a finite number.") from exc
    if not math.isfinite(number):
        raise ESPNDataError(f"{field} must be a finite number.")
    return number


def _object(value, field):
    if not isinstance(value, dict):
        raise ESPNDataError(f"{field} must be a JSON object.")
    return value


def _array(value, field):
    if not isinstance(value, list):
        raise ESPNDataError(f"{field} must be a JSON array.")
    return value


def _scope(league_id, season):
    league = _numeric_id(league_id, "League ID")
    year = _integer(season, "Season", minimum=2020)
    if year > 2100:
        raise ESPNDataError("Season is outside the supported range.")
    return league, year


def league_read_url(league_id, season):
    """Return the permitted ESPN league read endpoint."""
    league, year = _scope(league_id, season)
    return f"{BASE}/seasons/{year}/segments/0/leagues/{league}?view=mSettings&view=mTeam&view=mDraftDetail&view=mStatus"


def player_read_url(league_id, season):
    """Return the permitted ESPN player read endpoint."""
    league, year = _scope(league_id, season)
    return f"{BASE}/seasons/{year}/segments/0/leagues/{league}?view=kona_player_info"


def _verify_player_response_scope(payload, league, season, expected_url, observed_url):
    """Verify explicit identity fields or the adapter's exact player request URL.

    ESPN can return only ``players``. Such a response needs request metadata
    from the adapter. A caller must not infer or insert missing identity fields.
    """
    _object(payload, "ESPN player payload")
    league, season = _scope(league, season)
    if "id" in payload and _numeric_id(payload["id"], "Player response league ID") != league:
        raise ESPNDataError("The ESPN player payload identifies a different league scope.")
    if "seasonId" in payload and _scope(league, payload["seasonId"])[1] != season:
        raise ESPNDataError("The ESPN player payload identifies a different season scope.")
    if observed_url is not None and observed_url != expected_url:
        raise ESPNDataError("The verified player response URL does not match the requested league and season scope.")
    if ("id" not in payload or "seasonId" not in payload) and observed_url != expected_url:
        raise ESPNDataError("A player response without league or season identity requires its exact verified request URL.")
    if (_integer(payload.get("gameId", 1), "Player response game ID") != 1
            or _integer(payload.get("segmentId", 0), "Player response segment ID") != 0):
        raise ESPNDataError("The ESPN player payload is not a supported football league segment.")


def player_read_headers(season=None):
    """Request a broad player pool with projection statistics.

    The browser adapter must preserve the download time when it caches this
    response. ESPN does not supply a projection publication time here.
    """
    filters = {"limit": 10000, "sortDraftRanks": {"sortPriority": 100, "sortAsc": True, "value": "PPR"}}
    if season is not None:
        _scope(1, season)
    return {"x-fantasy-filter": json.dumps({"players": filters}, separators=(",", ":"))}


def _page_scope(page_url, target_team, observed_team_id):
    parsed = urlsplit(page_url)
    if (parsed.scheme != "https" or parsed.hostname != "fantasy.espn.com"
            or parsed.username or parsed.password or parsed.port not in (None, 443)
            or not parsed.path.startswith("/football/")):
        raise ESPNDataError("The observation must come from the ESPN football page.")
    query = parse_qs(parsed.query)
    def single(name):
        values = query.get(name, [])
        if len(values) != 1:
            raise ESPNDataError(f"The ESPN page must identify one {name}.")
        return values[0]
    league, season = _scope(single("leagueId"), single("seasonId"))
    if "teamId" in query:
        page_team = _numeric_id(single("teamId"), "Page team ID")
        if observed_team_id is not None and _numeric_id(observed_team_id, "Observed team ID") != page_team:
            raise ESPNDataError("The page and observed team identities conflict.")
    elif observed_team_id is not None:
        page_team = _numeric_id(observed_team_id, "Observed team ID")
    else:
        raise ESPNDataError("Verify the active team from the page or its My Team link.")
    if page_team != target_team:
        raise ESPNDataError("The observed team does not match the requested team.")
    return league, season, page_team


def _owner(number, count):
    rnd, offset = divmod(number - 1, count)
    return count - offset if rnd % 2 else offset + 1


def _rules(payload, target):
    settings = _object(payload.get("settings"), "League settings")
    draft = _object(settings.get("draftSettings"), "Draft settings")
    if str(draft.get("type", "")).upper() != "SNAKE":
        raise ESPNDataError("Only snake drafts are supported.")
    if (_integer(draft.get("keeperCount", 0), "Keeper count")
            or _integer(draft.get("keeperCountFuture", 0), "Future keeper count")
            or draft.get("isTradingEnabled") is True):
        raise ESPNDataError("Keeper leagues and traded draft picks are not supported.")
    if str(draft.get("leagueSubType", "NONE")).upper() not in ("NONE", ""):
        raise ESPNDataError("This draft subtype is not supported.")
    teams = _array(payload.get("teams"), "League teams")
    count = _integer(settings.get("size"), "League size", minimum=2)
    ids = [_numeric_id(_object(t, "Team").get("id"), "Team ID") for t in teams]
    if count != len(teams) or len(set(ids)) != count or target not in ids:
        raise ESPNDataError("The league must include every team exactly once.")
    detail = _object(payload.get("draftDetail"), "Draft detail")
    picks = _array(detail.get("picks"), "Draft picks")
    order = draft.get("pickOrder")
    if not order:
        first = [p for p in picks if _object(p, "Draft pick").get("roundId") == 1]
        first.sort(key=lambda p: _integer(p.get("overallPickNumber"), "Pick number", minimum=1))
        if [p.get("overallPickNumber") for p in first] != list(range(1, count + 1)):
            raise ESPNDataError("The full draft order is missing.")
        order = [p.get("teamId") for p in first]
    order = [_numeric_id(t, "Draft order team ID") for t in _array(order, "Draft order")]
    if len(order) != count or set(order) != set(ids):
        raise ESPNDataError("The draft order must contain every team exactly once.")
    roster = _object(settings.get("rosterSettings"), "Roster settings")
    raw_slots = _object(roster.get("lineupSlotCounts"), "Lineup slots")
    slots = {}
    for key, value in raw_slots.items():
        slot = _integer(key, "Lineup slot ID")
        value = _integer(value, "Lineup slot count")
        if value and slot not in SLOTS:
            raise ESPNDataError("The league uses an unsupported lineup slot.")
        if slot in SLOTS:
            slots[SLOTS[slot]] = value
    starters = {name: slots.get(name, 0) for name in (*POSITIONS.values(), "FLEX") if slots.get(name, 0)}
    rounds = sum(starters.values()) + slots.get("BN", 0)
    raw_caps = _object(roster.get("positionLimits"), "Position limits")
    caps = {}
    for pid, position in POSITIONS.items():
        if str(pid) not in raw_caps:
            raise ESPNDataError("A supported position limit is missing.")
        limit = _integer(raw_caps[str(pid)], "Position limit", minimum=-1)
        caps[position] = rounds if limit == -1 else limit
    rules = Rules(teams=count, slot=order.index(target) + 1, rounds=rounds, snake=True,
                  starters=starters, caps=caps, bench=slots.get("BN", 0), ir=slots.get("IR", 0),
                  flex_eligible=["RB", "WR", "TE"])
    names = {}
    for raw, team_id in zip(teams, ids):
        name = raw.get("name") or " ".join(str(raw.get(k) or "").strip() for k in ("location", "nickname")).strip()
        if not isinstance(name, str) or not name.strip():
            raise ESPNDataError("A team name is missing.")
        names[team_id] = name.strip()
        if raw.get("keepers"):
            raise ESPNDataError("Keeper leagues are not supported.")
    return rules, order, names, picks


def _scoring(payload):
    settings = _object(payload["settings"].get("scoringSettings"), "Scoring settings")
    if settings.get("scoringType", "H2H_POINTS") != "H2H_POINTS":
        raise ESPNDataError("Only head-to-head point scoring is supported.")
    items = _array(settings.get("scoringItems"), "Scoring items")
    if not items:
        raise ESPNDataError("League scoring items are missing.")
    result, seen = [], set()
    for raw in items:
        item = _object(raw, "Scoring item")
        stat = str(_integer(item.get("statId"), "Scoring statistic ID"))
        if stat in seen or item.get("isReverseItem") is True:
            raise ESPNDataError("Duplicate or reverse scoring items are not supported.")
        seen.add(stat)
        overrides = _object(item.get("pointsOverrides") or {}, "Scoring overrides")
        result.append((stat, _number(item.get("points"), "Scoring multiplier"),
                       {str(k): _number(v, "Position scoring multiplier") for k, v in overrides.items()}))
    return result


def _players(payload, season, scoring, needed):
    rows = _array(payload.get("players"), "Player pool")
    result, missing, seen = [], set(), set()
    for entry in rows:
        entry = _object(entry, "Player entry")
        raw = _object(entry.get("player", entry), "Player")
        pid = _numeric_id(raw.get("id"), "Player ID", player=True)
        if pid in seen:
            raise ESPNDataError("The player pool contains duplicate identifiers.")
        seen.add(pid)
        position_id = _integer(raw.get("defaultPositionId"), "Player position")
        if position_id not in POSITIONS:
            if pid in needed:
                raise ESPNDataError("A drafted player has an unsupported position.")
            continue
        ownership = _object(raw.get("ownership") or {}, "Player ownership")
        adp = _number(ownership.get("averageDraftPosition", 999), "Average draft position")
        adp = adp if 0 < adp < 999 else 999
        records = [r for r in _array(raw.get("stats", []), "Player statistics")
                   if isinstance(r, dict) and r.get("seasonId") == season and r.get("statSourceId") == 1
                   and r.get("statSplitTypeId") == 0 and r.get("scoringPeriodId") == 0]
        # ESPN can assign an ADP near 170 to unprojected free agents. ADP does
        # not prove that a season projection exists or make one safe to invent.
        required = pid in needed or entry.get("onTeamId", 0) not in (None, 0, "0")
        if not records:
            if required:
                missing.add(pid)
            continue
        if len(records) != 1:
            raise ESPNDataError("A player has conflicting full-season projection records.")
        stats = _object(records[0].get("stats"), "Full-season projection statistics")
        if not stats:
            if required:
                missing.add(pid)
            continue
        total = sum(_number(stats.get(stat, 0), "Projected statistic") * overrides.get(str(position_id), points)
                    for stat, points, overrides in scoring)
        if total < 0:
            raise ESPNDataError("Negative season totals are not supported by the draft model.")
        eligible = _array(raw.get("eligibleSlots"), "Player eligibility")
        positions = list(dict.fromkeys(PRIMARY_SLOTS[s] for s in eligible if s in PRIMARY_SLOTS))
        if POSITIONS[position_id] not in positions:
            raise ESPNDataError("The player has no verified eligibility for the primary position.")
        status = raw.get("injuryStatus")
        if not status:
            status = "ACTIVE" if raw.get("active") is True else "INACTIVE" if raw.get("active") is False else "UNKNOWN"
        result.append(Player(id=pid, name=raw.get("fullName"), position=POSITIONS[position_id],
                             eligible_positions=positions, team=str(raw.get("proTeamAbbreviation") or raw.get("proTeamId") or ""),
                             projection=round(total, 6), adp=adp, availability=status))
    if missing or needed - {p.id for p in result}:
        raise ESPNDataError("A required player has no matching full-season projection record.")
    if not result:
        raise ESPNDataError("The player pool has no usable season projections.")
    return result


def _name_key(name):
    value = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().casefold()
    return re.sub(r"[^a-z0-9]", "", value)


def _visible_picks(text, players, count):
    by_name = {}
    for player in players:
        by_name.setdefault(_name_key(player.name), []).append(player)
    def identify(name, position=None):
        matches = by_name.get(_name_key(name.strip()), [])
        if position:
            position = {"D/ST": "DST", "DEF": "DST"}.get(position, position)
            matches = [p for p in matches if position in p.eligible_positions]
        if len(matches) != 1:
            raise ESPNDataError("A visible pick does not identify one projected player.")
        return matches[0].id
    result = []
    # Accessibility snapshots prefix rows with a node number. Available-player
    # rows also contain QUEUE or DRAFT controls and cannot establish a pick.
    history_text = ""
    history_heading = re.search(r"\b(?:DRAFT HISTORY|PICK HISTORY|DRAFT RECAP)\b", text, re.I)
    if history_heading:
        history_text = text[history_heading.end():]
    for number, description in re.findall(r"^\s*\d+ row (\d+) (.+)$", history_text, re.M):
        if re.search(r"\b(?:QUEUE|DRAFT)\b", description):
            continue
        candidates = [p for p in players if description.startswith(p.name + " ")]
        if len(candidates) != 1:
            raise ESPNDataError("A visible history row does not identify one player.")
        result.append((int(number), candidates[0].id))
    activity = re.compile(r"(?:^|\n)\s*(?:\d+\s+text\s+|text\s+)?([^\n]+?)\s*/\s*"
                          r"[A-Z]{2,4}\s+(QB|RB|WR|TE|D/ST|DST|DEF|K)(?:,\s*[A-Z/]+)*\s+"
                          r"R(\d+),\s*P(\d+)\s*-", re.M)
    for name, position, rnd, offset in activity.findall(text):
        rnd, offset = int(rnd), int(offset)
        if rnd < 1 or not 1 <= offset <= count:
            raise ESPNDataError("A visible Activity pick has an invalid round or position.")
        result.append(((rnd - 1) * count + offset, identify(name, position)))
    return result


def normalize_espn_draft(league_payload, players_payload, *, team_id, visible_text,
                         page_url, observed_at, previous=None, observed_team_id=None,
                         projections_observed_at=None, player_response_url=None) -> LeagueSnapshot:
    """Build a complete draft snapshot from fresh browser observations.

    ``observed_team_id`` must come from a verified My Team link when the page
    URL lacks ``teamId``. The configured target alone does not prove identity.
    ``previous`` contributes only confirmed picks from the same draft scope.
    A cached player response must retain its actual download timestamp.
    A player-only response requires its exact verified request URL.
    """
    target = _numeric_id(team_id, "Requested team ID")
    league, season, verified_team = _page_scope(page_url, target, observed_team_id)
    if not isinstance(visible_text, str) or not visible_text.strip():
        raise ESPNDataError("The visible draft observation is empty.")
    _object(league_payload, "ESPN league payload")
    if _scope(league_payload.get("id"), league_payload.get("seasonId")) != (league, season):
        raise ESPNDataError("The ESPN payload and page identify different league or season scopes.")
    if league_payload.get("gameId", 1) != 1 or league_payload.get("segmentId", 0) != 0:
        raise ESPNDataError("The ESPN payload is not a supported football league segment.")
    _verify_player_response_scope(players_payload, league, season, player_read_url(league, season), player_response_url)
    rules, order, names, raw_picks = _rules(league_payload, target)
    if previous is not None:
        if (not isinstance(previous, LeagueSnapshot) or previous.league_id != league
                or previous.team_id != target or previous.season != season or previous.phase != "draft"
                or previous.source.provider != "espn_browser" or previous.source.synthetic
                or not previous.source.complete or previous.rules != rules
                or [(t.id, t.slot) for t in previous.teams] != [(t, i + 1) for i, t in enumerate(order)]):
            raise ESPNDataError("Previous picks belong to a different draft scope or rules.")
    confirmed = {}
    def add(number, pid, slot):
        if not 1 <= number <= rules.teams * rules.rounds or slot != _owner(number, rules.teams):
            raise ESPNDataError("A confirmed pick has an invalid number or snake owner.")
        pick = Pick(pick_no=number, player_id=pid, slot=slot)
        if number in confirmed and confirmed[number] != pick:
            raise ESPNDataError("Confirmed draft observations conflict at the same pick.")
        if any(p.player_id == pid and n != number for n, p in confirmed.items()):
            raise ESPNDataError("A player appears at more than one confirmed pick.")
        confirmed[number] = pick
    for pick in previous.picks if previous else []:
        add(pick.pick_no, pick.player_id, pick.slot)
    for raw in raw_picks:
        raw = _object(raw, "Draft pick")
        number = _integer(raw.get("overallPickNumber"), "Pick number", minimum=1)
        if not 1 <= number <= rules.teams * rules.rounds:
            raise ESPNDataError("An API pick is outside the configured draft.")
        owner = _numeric_id(raw.get("teamId"), "Pick team ID")
        if owner not in order or order.index(owner) + 1 != _owner(number, rules.teams):
            raise ESPNDataError("The API pick schedule conflicts with the snake draft order.")
        if raw.get("keeper"):
            raise ESPNDataError("Keeper picks are not supported.")
        rnd, offset = divmod(number - 1, rules.teams)
        if raw.get("roundId", rnd + 1) != rnd + 1 or raw.get("roundPickNumber", offset + 1) != offset + 1:
            raise ESPNDataError("The API round and overall pick numbers conflict.")
        value = raw.get("playerId")
        if value in (None, "", -1, "-1", 0, "0"):
            continue
        add(number, _numeric_id(value, "Drafted player ID", player=True), order.index(owner) + 1)
    players = _players(players_payload, season, _scoring(league_payload), {p.player_id for p in confirmed.values()})
    for number, pid in _visible_picks(visible_text, players, rules.teams):
        add(number, pid, _owner(number, rules.teams))
    total = rules.teams * rules.rounds
    clocks = {int(n) for n in re.findall(r"ON THE CLOCK:\s*PICK\s+(\d+)", visible_text, re.I)}
    complete_text = bool(re.search(r"\bDRAFT\s+(?:IS\s+)?COMPLETE\b|\bDRAFT\s+HAS\s+ENDED\b", visible_text, re.I))
    drafted = league_payload["draftDetail"].get("drafted") is True
    if len(clocks) > 1:
        raise ESPNDataError("Visible draft clocks conflict.")
    current = next(iter(clocks), None)
    if current is None:
        if not (complete_text or drafted):
            raise ESPNDataError("No verified current pick or completed draft is visible.")
        current = total + 1
    if not 1 <= current <= total + 1:
        raise ESPNDataError("The visible current pick is outside the configured draft.")
    if (complete_text or drafted) and current <= total:
        raise ESPNDataError("The completed draft status conflicts with the visible clock.")
    if sorted(confirmed) != list(range(1, current)):
        raise ESPNDataError("Draft history is incomplete or stale relative to the visible current pick.")
    complete = current == total + 1 and len(confirmed) == total
    if len(players) < total:
        raise ESPNDataError("The projected player pool cannot cover the configured draft.")
    enabled = bool(re.search(r"\bDISABLE\s+AUTOPICK\b", visible_text, re.I))
    disabled = bool(re.search(r"\bENABLE\s+AUTOPICK\b", visible_text, re.I))
    if enabled and disabled:
        raise ESPNDataError("Visible Autopick controls conflict.")
    source = Source(provider="espn_browser", observed_at=observed_at, complete=True,
                    synthetic=False, locks_verified=False,
                    projections_observed_at=projections_observed_at or observed_at,
                    notes=["Projection timestamps record the response download time, not the ESPN publication time.",
                           f"Excluded {len(players_payload['players']) - len(players)} player rows without usable supported season projections.",
                           "An excluded player cannot receive a recommendation. A confirmed or rostered exclusion blocks this snapshot.",
                           "Complete means the observed draft history is complete through the current pick. Weekly projections and locks are unverified."],
                    browser={"page_url": page_url, "league_id": league, "team_id": verified_team,
                             "current_pick": current, "autopick_enabled": True if enabled else False if disabled else None,
                             "draft_complete": complete})
    if previous and source.observed_at < previous.source.observed_at:
        raise ESPNDataError("The browser observation is older than the accepted snapshot.")
    if source.projections_observed_at > source.observed_at:
        raise ESPNDataError("The projection download time is later than the browser observation.")
    return LeagueSnapshot(league_id=league, team_id=target, season=season, phase="draft", source=source,
                          rules=rules, players=players, picks=[confirmed[n] for n in sorted(confirmed)],
                          teams=[Team(id=tid, name=names[tid], slot=slot,
                                      roster_ids=[p.player_id for _, p in sorted(confirmed.items()) if p.slot == slot])
                                 for slot, tid in enumerate(order, 1)])
