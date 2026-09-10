"""Verify portfolio isolation, bounded reads, and truthful data states."""

from datetime import timedelta
import hashlib
import json
import sqlite3

import pytest

from fantasy_football_manager.demo import make_demo
from fantasy_football_manager.models import ManagerConfig
from fantasy_football_manager.portfolio import MAX_PROPOSALS_PER_TEAM, Portfolio


def store(tmp_path, key="one", *, league=None, snapshot=None, config=None):
    directory = tmp_path / key
    directory.mkdir()
    snapshot = snapshot or make_demo()
    snapshot.league_id = league or key
    snapshot.own_team().name = f"Team {key}"
    config = config or ManagerConfig()
    with sqlite3.connect(directory / "manager.sqlite3") as db:
        db.execute("CREATE TABLE state(id INTEGER PRIMARY KEY, snapshot TEXT, revision INTEGER, config TEXT, config_revision INTEGER)")
        db.execute("INSERT INTO state VALUES(1,?,3,?,2)", (snapshot.model_dump_json(), config.model_dump_json()))
        db.execute("CREATE TABLE proposals(id TEXT PRIMARY KEY, action TEXT, payload TEXT, revision INTEGER, config_revision INTEGER, result TEXT)")
    return snapshot


def manifest(tmp_path, *keys, **extra):
    value = {"schema_version": 1, "teams": [{"key": key, "label": f"Saved {key}", "sport": "football",
              "provider": "espn", "data_dir": key} for key in keys], **extra}
    path = tmp_path / "portfolio.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def http_table(tmp_path, key="one"):
    db = sqlite3.connect(tmp_path / key / "manager.sqlite3")
    db.execute("""CREATE TABLE espn_http_proposals(id TEXT PRIMARY KEY, action TEXT, league_id TEXT,
        team_id TEXT, season INTEGER, week INTEGER, revision INTEGER, config_revision INTEGER,
        baseline TEXT, decision TEXT, status TEXT, authorized_at TEXT, response TEXT, result TEXT)""")
    return db


def add_http(db, snapshot, *, pid="proposal-1", status="pending", revision=3, config_revision=2,
             week=None, league=None, payload=None, result=None):
    decision = {"payload": payload or {"player_id": snapshot.own_team().roster_ids[0]}, "mode": "review",
                "credential_file": "/private/credential-file", "token": "secret-token"}
    db.execute("INSERT INTO espn_http_proposals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (pid, "free_agent_add", league or snapshot.league_id, snapshot.team_id, snapshot.season,
                week or snapshot.week, revision, config_revision, '{"secret":"private-baseline"}',
                json.dumps(decision), status, None, '{"cookie":"private-cookie"}', json.dumps(result) if result else None))


def test_multiteam_reads_are_isolated_and_include_limits(tmp_path):
    config = ManagerConfig()
    config.automation.preset = "custom"
    config.automation.actions["set_lineup"] = "automatic"
    snapshot = store(tmp_path, config=config)
    store(tmp_path, "two")
    portfolio = Portfolio(manifest(tmp_path, "one", "two"))
    overview = portfolio.overview()
    assert overview["summary"]["total_teams"] == 2
    assert overview["read_only"] is True
    assert {team["team_key"] for team in overview["teams"]} == {"one", "two"}
    detail = portfolio.team("one")
    assert {player["team_key"] for player in detail["roster"]} == {"one"}
    assert len(detail["roster"]) == len(snapshot.own_team().roster_ids)
    assert detail["policy"]["effective_modes"]["set_lineup"] == "automatic"
    assert detail["policy"]["limits"]["drop_mode"] == "listed_only"
    assert portfolio.analysis("one")["status"] == "ok"
    assert portfolio.players(team_key="two")["total"] == 14


def test_no_database_or_directory_writes_and_no_manager_init(tmp_path, monkeypatch):
    store(tmp_path)
    path = manifest(tmp_path, "one", "missing")
    def fingerprints():
        return {str(p.relative_to(tmp_path)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in tmp_path.rglob("*") if p.is_file()}
    before = fingerprints()
    def fail(*args, **kwargs):
        raise AssertionError("Manager must not initialize during a portfolio read.")
    monkeypatch.setattr("fantasy_football_manager.store.Manager.__init__", fail)
    calls = []
    connect = sqlite3.connect
    def observed_connect(*args, **kwargs):
        calls.append((args, kwargs))
        connection = connect(*args, **kwargs)
        return connection
    monkeypatch.setattr("fantasy_football_manager.portfolio.sqlite3.connect", observed_connect)
    portfolio = Portfolio(path)
    for result in (portfolio.overview(), portfolio.team("one"), portfolio.players(), portfolio.proposals(), portfolio.analysis("one")):
        json.dumps(result, allow_nan=False)
    assert all("mode=ro" in args[0] and kwargs["uri"] is True for args, kwargs in calls)
    assert fingerprints() == before
    assert not (tmp_path / "missing").exists()


def test_legacy_manifest_uses_stable_context_keys_and_relative_paths(tmp_path):
    snapshot = store(tmp_path)
    data = {"leagues": [{"league_id": snapshot.league_id, "team_id": snapshot.team_id, "season": snapshot.season,
                         "week": snapshot.week, "data_dir": "one"}],
            "credential_file": "/private/secrets.json", "browser_data_dir": "/private/browser"}
    path = tmp_path / "coordinator.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    first = Portfolio(path).overview()["teams"][0]
    data["leagues"][0]["week"] += 1
    path.write_text(json.dumps(data), encoding="utf-8")
    assert Portfolio(path).overview()["teams"][0]["team_key"] == first["team_key"]
    assert first["data_status"] == "ready"
    assert first["league_name"] == f"League {snapshot.league_id}"
    assert first["league_key"].startswith("league-")
    assert Portfolio(path).overview()["teams"][0]["league_key"] == first["league_key"]
    assert "private" not in json.dumps(first)


@pytest.mark.parametrize("change", ["duplicate_key", "duplicate_directory", "duplicate_context", "too_many", "missing_key", "bad_version"])
def test_invalid_manifest_is_rejected_without_path_disclosure(tmp_path, change):
    items = [{"key": "one", "data_dir": "one"}, {"key": "two", "data_dir": "two"}]
    data = {"schema_version": 1, "teams": items}
    if change == "duplicate_key":
        items[1]["key"] = "one"
    elif change == "duplicate_directory":
        items[1]["data_dir"] = "one"
    elif change == "duplicate_context":
        for item in items:
            item.update(league_id="1", team_id="2", season=2026)
    elif change == "too_many":
        data["teams"] = [{"key": f"team-{i}", "data_dir": str(i)} for i in range(101)]
    elif change == "missing_key":
        del items[0]["key"]
    elif change == "bad_version":
        data["schema_version"] = 2
    path = tmp_path / "private-manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="^The portfolio manifest is invalid or unavailable.$"):
        Portfolio(path)


def test_duplicate_observed_contexts_are_invalid_for_every_endpoint(tmp_path):
    store(tmp_path, league="same")
    store(tmp_path, "two", league="same")
    portfolio = Portfolio(manifest(tmp_path, "one", "two"))
    assert {team["data_status"] for team in portfolio.overview()["teams"]} == {"invalid"}
    assert portfolio.team("one")["roster"] == []
    assert portfolio.players()["total"] == 0


def test_two_managed_teams_in_one_league_share_a_stable_league_key(tmp_path):
    first = store(tmp_path, league="shared-league")
    second = make_demo()
    second.team_id = second.teams[1].id
    second.rules.slot = second.teams[1].slot
    store(tmp_path, "two", league=first.league_id, snapshot=second)
    portfolio = Portfolio(manifest(tmp_path, "one", "two"))
    teams = portfolio.overview()["teams"]
    assert all(team["data_status"] == "ready" for team in teams)
    assert len({team["team_key"] for team in teams}) == 2
    assert len({team["league_key"] for team in teams}) == 1
    assert teams[0]["league_key"] is not None
    assert {team["league_name"] for team in teams} == {"League shared-league"}
    assert portfolio.team("one")["team"]["league_key"] == teams[0]["league_key"]


def test_distinct_leagues_with_identical_names_have_distinct_league_keys(tmp_path):
    store(tmp_path)
    store(tmp_path, "two")
    path = manifest(tmp_path, "one", "two")
    document = json.loads(path.read_text())
    for entry in document["teams"]:
        entry["league_name"] = "Fictional Football League"
    path.write_text(json.dumps(document), encoding="utf-8")
    teams = Portfolio(path).overview()["teams"]
    assert len({team["league_name"] for team in teams}) == 1
    assert len({team["league_key"] for team in teams}) == 2


def test_missing_store_can_report_explicit_league_identity(tmp_path):
    path = manifest(tmp_path, "missing", "unknown", "unsupported")
    document = json.loads(path.read_text())
    document["teams"][0].update(league_id="fictional-league", team_id="fictional-team", season=2026)
    document["teams"][2]["sport"] = "basketball"
    path.write_text(json.dumps(document), encoding="utf-8")
    teams = Portfolio(path).overview()["teams"]
    assert teams[0]["data_status"] == "missing"
    assert teams[0]["league_key"].startswith("league-")
    assert teams[0]["league_name"] == "League fictional-league"
    assert teams[1]["league_key"] is None
    assert teams[2]["league_key"] is None


def test_mismatched_store_does_not_break_other_teams(tmp_path):
    store(tmp_path)
    store(tmp_path, "two")
    path = manifest(tmp_path, "one", "two", "missing")
    data = json.loads(path.read_text())
    data["teams"][0].update(league_id="wrong", team_id="wrong", season=2026)
    path.write_text(json.dumps(data), encoding="utf-8")
    portfolio = Portfolio(path)
    teams = {team["team_key"]: team for team in portfolio.overview()["teams"]}
    assert teams["one"]["data_status"] == "invalid"
    assert teams["two"]["data_status"] == "ready"
    assert teams["missing"]["data_status"] == "missing"
    assert portfolio.team("one")["roster"] == []


@pytest.mark.parametrize("corruption", ["sqlite", "snapshot", "config", "oversized", "nan", "null"])
def test_corrupt_input_is_bounded_and_safe(tmp_path, corruption):
    store(tmp_path)
    db_path = tmp_path / "one" / "manager.sqlite3"
    if corruption == "sqlite":
        db_path.write_bytes(b"not a database with secret-cookie")
    else:
        with sqlite3.connect(db_path) as db:
            if corruption == "snapshot":
                db.execute("UPDATE state SET snapshot='private-cookie'")
            elif corruption == "config":
                db.execute("UPDATE state SET config='{}invalid'")
            elif corruption == "oversized":
                db.execute("UPDATE state SET config=?", ('"' + "x" * 70000 + '"',))
            elif corruption == "nan":
                db.execute("UPDATE state SET config=?", ('{"schema_version":NaN}',))
            else:
                db.execute("UPDATE state SET snapshot=NULL")
    result = Portfolio(manifest(tmp_path, "one")).team("one")
    assert result["team"]["data_status"] == ("missing" if corruption == "null" else "invalid")
    assert "private-cookie" not in json.dumps(result)
    assert result["roster"] == []


def test_stale_missing_projection_and_unverified_lock_states(tmp_path):
    snapshot = make_demo()
    snapshot.source.observed_at -= timedelta(hours=1)
    store(tmp_path, snapshot=snapshot)
    second = make_demo()
    second.source.locks_verified = False
    second.players[0].weekly_projection = None
    store(tmp_path, "two", snapshot=second)
    portfolio = Portfolio(manifest(tmp_path, "one", "two"))
    teams = portfolio.overview()["teams"]
    assert teams[0]["data_status"] == "stale"
    assert portfolio.analysis("one")["status"] == "incomplete"
    assert teams[1]["locks_verified"] is False
    assert teams[1]["missing_projection_count"] == 1
    assert portfolio.analysis("two")["status"] == "incomplete"
    assert portfolio.team("two")["roster"][0]["weekly_projection"] is None


def test_unknown_sport_and_provider_are_explicitly_unsupported(tmp_path):
    path = manifest(tmp_path, "basketball", "unknown")
    data = json.loads(path.read_text())
    data["teams"][0]["sport"] = "basketball"
    data["teams"][1]["provider"] = "other"
    path.write_text(json.dumps(data), encoding="utf-8")
    portfolio = Portfolio(path)
    overview = portfolio.overview()
    assert overview["supported_sports"] == ["football"]
    assert {team["data_status"] for team in overview["teams"]} == {"unsupported"}
    assert portfolio.overview(sport="basketball")["summary"]["total_teams"] == 1
    assert portfolio.analysis("basketball")["status"] == "unavailable"
    assert not (tmp_path / "basketball").exists()


def test_saved_proposals_preserve_status_scope_and_staleness(tmp_path):
    snapshot = store(tmp_path)
    with http_table(tmp_path) as db:
        add_http(db, snapshot, pid="prepared")
        add_http(db, snapshot, pid="awaiting", status="awaiting_verification")
        add_http(db, snapshot, pid="executed", status="executed", result={"status": "confirmed"})
        add_http(db, snapshot, pid="confirmed", status="confirmed", revision=2)
        add_http(db, snapshot, pid="old-week", week=snapshot.week + 1)
        add_http(db, snapshot, pid="other-league", league="other")
    portfolio = Portfolio(manifest(tmp_path, "one"))
    result = portfolio.proposals()
    records = {item["id"]: item for item in result["proposals"]}
    assert result["total"] == 5
    assert records["executed"]["status"] == "executed"
    assert records["confirmed"]["status"] == "confirmed"
    assert records["confirmed"]["is_current"] is False
    assert records["old-week"]["is_current"] is False
    assert records["awaiting"]["is_current"] is True
    assert all(item["source"] == "http" and item["scope"] == "espn_http" for item in records.values())
    assert all(item["created_at"] is None for item in records.values())
    assert portfolio.overview()["teams"][0]["pending_count"] == 3
    assert portfolio.proposals(status="confirmed")["total"] == 1


def test_proposal_whitelist_excludes_secrets_and_arbitrary_payload_keys(tmp_path):
    snapshot = store(tmp_path)
    pid = snapshot.own_team().roster_ids[0]
    payload = {"player_id": pid, "drop_id": "private-cookie", "bid": 7,
               "credential_file": "/private/path", "cookie": "private-cookie", "headers": {"token": "private-token"},
               "lineup": {"QB1": pid, "private-slot": "private-cookie"}}
    with http_table(tmp_path) as db:
        add_http(db, snapshot, payload=payload)
    result = Portfolio(manifest(tmp_path, "one")).proposals()
    assert result["proposals"][0]["payload"] == {"player_id": pid, "bid": 7, "lineup": {"QB1": pid}}
    text = json.dumps(result)
    for forbidden in ("private", "credential", "cookie", "token", "response", "baseline"):
        assert forbidden not in text


def test_legacy_proposals_only_expose_proven_current_context(tmp_path):
    snapshot = store(tmp_path)
    with sqlite3.connect(tmp_path / "one" / "manager.sqlite3") as db:
        for pid, revision, config_revision in [("current", 3, 2), ("old-context", 1, 1), ("old-config", 3, 1)]:
            db.execute("INSERT INTO proposals VALUES(?,?,?,?,?,NULL)",
                       (pid, "set_lineup", json.dumps({"lineup": snapshot.own_team().lineup}), revision, config_revision))
    result = Portfolio(manifest(tmp_path, "one")).proposals()
    assert result["total"] == 1
    assert result["proposals"][0]["id"] == "current"
    assert result["proposals"][0]["status"] == "prepared"
    assert result["proposals"][0]["scope"] == "synthetic_demo_only"


def test_proposal_window_reports_truncation_and_exact_summary_count(tmp_path):
    snapshot = store(tmp_path)
    with http_table(tmp_path) as db:
        for i in range(MAX_PROPOSALS_PER_TEAM + 7):
            add_http(db, snapshot, pid=f"proposal-{i:04}")
    portfolio = Portfolio(manifest(tmp_path, "one"))
    result = portfolio.proposals(limit=200, offset=450)
    assert len(result["proposals"]) == 50
    assert result["total"] == MAX_PROPOSALS_PER_TEAM
    assert result["truncated"] is True
    assert result["total_scope"] == "loaded_records"
    assert portfolio.overview()["teams"][0]["proposal_count"] == MAX_PROPOSALS_PER_TEAM + 7


def test_player_search_pagination_and_ownership_do_not_mix_leagues(tmp_path):
    store(tmp_path)
    store(tmp_path, "two")
    portfolio = Portfolio(manifest(tmp_path, "one", "two"))
    rows = portfolio.players(position="WR", query="fictional wr", limit=2, offset=1)
    assert rows["total"] == 8
    assert len(rows["players"]) == 2
    assert all(item["owned"] and item["position"] == "WR" for item in rows["players"])
    whole = portfolio.players(team_key="one", rostered_only=False, limit=200)
    assert whole["total"] == 358
    assert {item["roster_status"] for item in whole["players"]} == {"managed_team", "opponent", "free_agent"}
    assert portfolio.players(query="not present")["total"] == 0
    assert portfolio.players(offset=100000)["players"] == []


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": 201}, {"limit": True}, {"offset": -1}, {"offset": 100001}, {"offset": "1"}])
def test_bad_pagination_is_rejected(kwargs):
    portfolio = Portfolio(demo=True)
    with pytest.raises(ValueError):
        portfolio.players(**kwargs)
    with pytest.raises(ValueError):
        portfolio.proposals(**kwargs)


@pytest.mark.parametrize("team_key", ["../private", "/private/path", "unknown", None, 3])
def test_unknown_team_is_not_a_file_path(team_key):
    portfolio = Portfolio(demo=True)
    with pytest.raises(ValueError, match="^Unknown managed team.$"):
        portfolio.team(team_key)
    with pytest.raises(ValueError, match="^Unknown managed team.$"):
        portfolio.analysis(team_key)


def test_demo_is_fictional_and_never_creates_a_store(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    portfolio = Portfolio(demo=True)
    overview = portfolio.overview()
    assert overview["source_mode"] == "demo"
    assert overview["summary"]["total_teams"] == 5
    assert all(team["demo"] and team["synthetic"] for team in overview["teams"])
    assert portfolio.players()["total"] == 70
    assert portfolio.proposals()["total"] == 3
    assert portfolio.analysis("westside-union")["status"] == "incomplete"
    for team in overview["teams"]:
        json.dumps(portfolio.team(team["team_key"]), allow_nan=False)
        json.dumps(portfolio.analysis(team["team_key"]), allow_nan=False)
    assert list(tmp_path.iterdir()) == []


def test_unconfigured_portfolio_has_explicit_empty_state():
    portfolio = Portfolio()
    assert portfolio.overview()["configuration_required"] is True
    assert portfolio.overview()["summary"]["total_teams"] == 0
    assert portfolio.players()["players"] == []
    assert portfolio.proposals()["proposals"] == []


def test_draft_read_is_preserved_without_starting_simulations(tmp_path):
    store(tmp_path, snapshot=make_demo("draft"))
    portfolio = Portfolio(manifest(tmp_path, "one"))
    assert portfolio.team("one")["team"]["phase"] == "draft"
    result = portfolio.analysis("one")
    assert result["status"] == "unavailable"
    assert "draft MCP tools" in result["errors"][0]


def review_fixture(tmp_path):
    from test_espn_http_policy import SWAP, automatic_config, http_snapshot
    snapshot = http_snapshot()
    config = automatic_config()
    config.automation.preset = "review"
    store(tmp_path, snapshot=snapshot, league=snapshot.league_id, config=config)
    with http_table(tmp_path) as db:
        add_http(db, snapshot, payload={"lineup": SWAP})
        db.execute("UPDATE espn_http_proposals SET action='set_lineup'")
    return Portfolio(manifest(tmp_path, "one")), snapshot


def test_private_review_material_is_exact_current_and_read_only(tmp_path):
    from test_espn_http_policy import SWAP
    portfolio, snapshot = review_fixture(tmp_path)
    database = tmp_path / "one" / "manager.sqlite3"
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    material = portfolio._http_review_material("one", "proposal-1")
    assert material["proposal"]["payload"] == {"lineup": SWAP}
    assert material["proposal"]["mode"] == "review"
    assert material["snapshot"].league_id == snapshot.league_id
    assert material["data_dir"] == tmp_path / "one"
    assert material["fingerprint"] == portfolio._http_review_material("one", "proposal-1")["fingerprint"]
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert "private" not in json.dumps(material["proposal"])


@pytest.mark.parametrize("change", ["status", "revision", "config_revision", "week", "league", "mode", "paused", "stale", "lock", "payload", "decision_mode"])
def test_private_review_rejects_invalid_or_changed_inputs(tmp_path, change):
    portfolio, snapshot = review_fixture(tmp_path)
    with sqlite3.connect(tmp_path / "one" / "manager.sqlite3") as db:
        if change in {"status", "revision", "config_revision", "week", "league"}:
            statements = {"status": "status='awaiting_verification'", "revision": "revision=2", "config_revision": "config_revision=1",
                          "week": f"week={snapshot.week + 1}", "league": "league_id='other'"}
            db.execute(f"UPDATE espn_http_proposals SET {statements[change]}")
        elif change in {"mode", "paused"}:
            config = json.loads(db.execute("SELECT config FROM state").fetchone()[0])
            if change == "mode":
                config["automation"]["preset"] = "bounded_automation"
            else:
                config["automation"]["paused"] = True
            db.execute("UPDATE state SET config=?", (json.dumps(config),))
        elif change in {"stale", "lock"}:
            if change == "stale":
                snapshot.source.observed_at -= timedelta(hours=1)
            else:
                snapshot.source.locks_verified = False
            db.execute("UPDATE state SET snapshot=?", (snapshot.model_dump_json(),))
        else:
            decision = json.loads(db.execute("SELECT decision FROM espn_http_proposals").fetchone()[0])
            if change == "payload":
                decision["payload"]["credential_file"] = "/private/path"
            else:
                decision["mode"] = "automatic"
            db.execute("UPDATE espn_http_proposals SET decision=?", (json.dumps(decision),))
    with pytest.raises(ValueError, match="^This proposal is not available for review.$"):
        portfolio._http_review_material("one", "proposal-1")


def test_private_review_cannot_route_a_proposal_to_another_team(tmp_path):
    portfolio, snapshot = review_fixture(tmp_path)
    store(tmp_path, "two")
    portfolio = Portfolio(manifest(tmp_path, "one", "two"))
    with pytest.raises(ValueError, match="^This proposal is not available for review.$"):
        portfolio._http_review_material("two", "proposal-1")
    with pytest.raises(ValueError, match="^This proposal is not available for review.$"):
        Portfolio(demo=True)._http_review_material("northside-wolves", "fictional-proposal-1")


def test_timestamp_only_refresh_preserves_review_but_changed_projection_does_not(tmp_path):
    portfolio, snapshot = review_fixture(tmp_path)
    before = portfolio._http_review_material("one", "proposal-1")["fingerprint"]
    snapshot.source.observed_at += timedelta(seconds=1)
    snapshot.source.projections_observed_at = snapshot.source.observed_at
    with sqlite3.connect(tmp_path / "one" / "manager.sqlite3") as db:
        db.execute("UPDATE state SET snapshot=?", (snapshot.model_dump_json(),))
    assert portfolio._http_review_material("one", "proposal-1")["fingerprint"] == before
    snapshot.players[0].weekly_projection += .001
    with sqlite3.connect(tmp_path / "one" / "manager.sqlite3") as db:
        db.execute("UPDATE state SET snapshot=?", (snapshot.model_dump_json(),))
    assert portfolio._http_review_material("one", "proposal-1")["fingerprint"] != before


def test_nonfinite_derived_totals_are_unknown_and_not_invalid_json(tmp_path):
    snapshot = make_demo()
    for player in snapshot.players:
        player.weekly_projection = 1e308
    store(tmp_path, snapshot=snapshot)
    result = Portfolio(manifest(tmp_path, "one")).analysis("one")
    json.dumps(result, allow_nan=False)
    assert result["status"] == "incomplete"
    assert result["current_projected_points"] is None


def test_demo_pending_proposals_are_legal_changes():
    from fantasy_football_manager.policy import check_action
    portfolio = Portfolio(demo=True)
    for frame in portfolio._demo_frames:
        for proposal in frame.proposals:
            if proposal["status"] == "prepared":
                assert proposal["payload"]["lineup"] != frame.snapshot.own_team().lineup
                assert check_action(frame.snapshot, frame.config, proposal["action"], proposal["payload"])["mode"] == "review"
