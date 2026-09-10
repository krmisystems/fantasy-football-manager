"""Verify exact dashboard approvals with fictional data and a fake ESPN provider."""

import asyncio
from contextlib import contextmanager
import json
import threading

import pytest

from fantasy_football_manager.dashboard import create_http_server
from fantasy_football_manager.dashboard_actions import DashboardActionError, DashboardActions
from fantasy_football_manager.portfolio import Portfolio
from test_dashboard import request


def demo_actions():
    portfolio = Portfolio(demo=True)
    return portfolio, DashboardActions(portfolio)


def test_demo_approval_changes_only_the_exact_fictional_lineup():
    portfolio, actions = demo_actions()
    revision = portfolio._demo_frames[0].revision
    original = portfolio.team("northside-wolves")
    other = portfolio.team("sunday-pilots")
    review = actions.review("northside-wolves", "fictional-proposal-1")
    assert review["proposal"]["mode"] == "review" and review["demo"] is True
    receipt = actions.submit("northside-wolves", "fictional-proposal-1", review["review_nonce"], True)
    assert receipt["status"] == "confirmed" and receipt["demo"] is True
    assert receipt["live_actions"] is False and receipt["retry_allowed"] is False
    updated = portfolio.team("northside-wolves")
    assert portfolio._demo_frames[0].revision == revision + 1
    assert {player["id"]: player["slot"] for player in updated["roster"]} != {player["id"]: player["slot"] for player in original["roster"]}
    assert portfolio.team("sunday-pilots")["roster"] == other["roster"]
    with pytest.raises(DashboardActionError, match="already used"):
        actions.submit("northside-wolves", "fictional-proposal-1", review["review_nonce"], True)
    with pytest.raises(DashboardActionError, match="not available"):
        actions.review("northside-wolves", "fictional-proposal-1")


def test_nonce_rejects_wrong_scope_and_expires():
    portfolio, actions = demo_actions()
    now = [10.0]
    actions.clock = lambda: now[0]
    review = actions.review("northside-wolves", "fictional-proposal-1")
    with pytest.raises(DashboardActionError, match="already used"):
        actions.submit("sunday-pilots", "fictional-proposal-3", review["review_nonce"], True)
    with pytest.raises(DashboardActionError, match="already used"):
        actions.submit("northside-wolves", "fictional-proposal-1", review["review_nonce"], True)
    review = actions.review("northside-wolves", "fictional-proposal-1")
    now[0] = 131.0
    with pytest.raises(DashboardActionError, match="expired"):
        actions.submit("northside-wolves", "fictional-proposal-1", review["review_nonce"], True)


def test_changed_proposal_or_config_cannot_use_prior_consent():
    portfolio, actions = demo_actions()
    review = actions.review("northside-wolves", "fictional-proposal-1")
    portfolio._demo_frames[0].proposals[0]["summary"] = "Changed review text"
    with pytest.raises(DashboardActionError, match="changed"):
        actions.submit("northside-wolves", "fictional-proposal-1", review["review_nonce"], True)
    review = actions.review("northside-wolves", "fictional-proposal-1")
    portfolio._demo_frames[0].config_revision += 1
    with pytest.raises(DashboardActionError, match="not available"):
        actions.submit("northside-wolves", "fictional-proposal-1", review["review_nonce"], True)


def test_false_confirmation_and_concurrent_team_action_are_blocked():
    portfolio, actions = demo_actions()
    review = actions.review("northside-wolves", "fictional-proposal-1")
    with pytest.raises(DashboardActionError, match="Confirm"):
        actions.submit("northside-wolves", "fictional-proposal-1", review["review_nonce"], False)
    lock = actions._team_locks["northside-wolves"]
    lock.acquire()
    try:
        with pytest.raises(DashboardActionError, match="in progress"):
            actions.submit("northside-wolves", "fictional-proposal-1", review["review_nonce"], True)
    finally:
        lock.release()


@contextmanager
def action_server(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "index.html").write_text("<!doctype html><title>Fictional portfolio</title>", encoding="utf-8")
    server = create_http_server(demo=True, enable_actions=True, port=0, asset_root=assets)
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    worker.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def post(server, route, value, *, headers=None):
    session = json.loads(request(server, "/api/session")[2])
    standard = {"Content-Type": "application/json", "X-FFM-CSRF": session["csrf_token"],
                "Origin": f"http://127.0.0.1:{server.server_port}"}
    standard.update(headers or {})
    return request(server, route, method="POST", headers=standard, body=json.dumps(value).encode())


def test_http_exact_review_then_submit(tmp_path):
    with action_server(tmp_path) as server:
        session = json.loads(request(server, "/api/session")[2])
        assert session["actions_enabled"] is True and session["demo"] is True and session["read_only"] is False
        assert json.loads(request(server, "/api/health")[2])["read_only"] is False
        value = {"team_key": "northside-wolves", "proposal_id": "fictional-proposal-1"}
        status, _, body = post(server, "/api/review", value)
        assert status == 200
        review = json.loads(body)
        submission = {**value, "review_nonce": review["review_nonce"], "confirmation": True}
        status, _, body = post(server, "/api/submit", submission)
        assert status == 200 and json.loads(body)["status"] == "confirmed"
        assert post(server, "/api/submit", submission)[0] == 409


@pytest.mark.parametrize("headers", [
    {"Origin": "https://evil.example"}, {"Origin": "null"}, {"X-FFM-CSRF": "wrong"},
    {"Content-Type": "text/plain"}, {"X-FFM-CSRF": "\u00e9"},
])
def test_http_approval_requires_origin_json_and_session(tmp_path, headers):
    with action_server(tmp_path) as server:
        value = {"team_key": "northside-wolves", "proposal_id": "fictional-proposal-1"}
        assert post(server, "/api/review", value, headers=headers)[0] in {400, 403}


def test_http_approval_rejects_missing_origin_extra_keys_and_duplicate_json_keys(tmp_path):
    with action_server(tmp_path) as server:
        session = json.loads(request(server, "/api/session")[2])
        headers = {"Content-Type": "application/json", "X-FFM-CSRF": session["csrf_token"]}
        body = b'{"team_key":"northside-wolves","proposal_id":"fictional-proposal-1"}'
        assert request(server, "/api/review", method="POST", headers=headers, body=body)[0] == 403
        headers["Origin"] = f"http://127.0.0.1:{server.server_port}"
        duplicate = body[:-1] + b',"team_key":"sunday-pilots"}'
        assert request(server, "/api/review", method="POST", headers=headers, body=duplicate)[0] == 400
        value = {"team_key": "northside-wolves", "proposal_id": "fictional-proposal-1", "credential_file": "/private/token.json"}
        assert post(server, "/api/review", value)[0] == 400


def live_fixture(tmp_path, *, keep_lease=False, waiver=False):
    from fantasy_football_manager.espn_http_season import ESPNHTTPSeason
    from fantasy_football_manager.espn_service import ESPNService
    from test_espn_http_service import FakeESPN, case

    async def setup():
        world = FakeESPN()
        world.projection(103, 30)
        world.projection(102, 20)
        if waiver:
            world.projection(109, 40)
            next(row for row in world.pool["players"] if row["id"] == 109)["status"] = "WAIVERS"
            world.post_behavior = "pending"
        service, adapter, world = await case(tmp_path / "team", world=world)
        _, config, _, revision = service.manager.require_state()
        config.automation.preset = "review"
        config.limits.allowed_drop_ids = ["103"]
        service.manager.update_config(config.model_dump(mode="json"), revision)
        proposal = service.http_actions.prepare("waiver_claim", {"player_id": "109", "drop_id": "103", "bid": 3}) if waiver else (
            service.http_actions.prepare("set_lineup", {"lineup": {"RB1": "103", "FLEX1": "102"}}))
        if not keep_lease:
            await adapter.close()
        return service, world, proposal

    existing, world, proposal = asyncio.run(setup())
    manifest = tmp_path / "portfolio.json"
    manifest.write_text(json.dumps({"schema_version": 1, "teams": [{"key": "team-a", "data_dir": "team", "provider": "espn"}]}), encoding="utf-8")
    instances = []

    def factory(data_dir, **options):
        assert options == {"transport": "http", "credential_file": None, "auto_rollover": False}
        adapter = ESPNHTTPSeason(data_dir, client=world)
        service = ESPNService(data_dir, browser=adapter, transport="http", auto_rollover=False)
        instances.append(service)
        return service

    portfolio = Portfolio(manifest)
    actions = DashboardActions(portfolio, service_factory=factory)
    return portfolio, actions, existing, world, proposal, instances


def test_existing_http_policy_submits_once_and_preserves_worker_connection(tmp_path):
    portfolio, actions, existing, world, proposal, instances = live_fixture(tmp_path)
    connection = existing.saved_connection()
    with existing.manager.transaction() as db:
        old_status = db.execute("SELECT status FROM espn_runtime WHERE id=1").fetchone()["status"]
    review = actions.review("team-a", proposal["proposal_id"])
    assert instances == [] and world.posts == []
    assert str(tmp_path) not in json.dumps(review)
    receipt = actions.submit("team-a", proposal["proposal_id"], review["review_nonce"], True)
    assert receipt["status"] == "confirmed", receipt
    assert len(world.posts) == 1 and len(instances) == 1
    assert existing.saved_connection() == connection
    with existing.manager.transaction() as db:
        assert db.execute("SELECT status FROM espn_runtime WHERE id=1").fetchone()["status"] == old_status
    assert instances[0].browser._lease is None
    with pytest.raises(DashboardActionError):
        actions.submit("team-a", proposal["proposal_id"], review["review_nonce"], True)
    assert len(world.posts) == 1


def test_existing_http_lease_blocks_second_service_without_post(tmp_path):
    _, actions, existing, world, proposal, instances = live_fixture(tmp_path, keep_lease=True)
    try:
        review = actions.review("team-a", proposal["proposal_id"])
        receipt = actions.submit("team-a", proposal["proposal_id"], review["review_nonce"], True)
        assert receipt["status"] == "busy"
        assert world.posts == [] and instances[0].browser._lease is None
        assert existing.browser._lease is not None
    finally:
        asyncio.run(existing.browser.close())


def test_timeout_after_fake_post_is_unknown_without_retry(tmp_path):
    _, actions, _, world, proposal, _ = live_fixture(tmp_path)
    world.post_behavior = "apply_then_timeout"
    review = actions.review("team-a", proposal["proposal_id"])
    receipt = actions.submit("team-a", proposal["proposal_id"], review["review_nonce"], True)
    assert receipt["status"] == "unknown" and receipt["retry_allowed"] is False
    assert len(world.posts) == 1


def test_terminal_espn_rejection_stays_distinct_from_unknown(tmp_path):
    _, actions, existing, world, proposal, _ = live_fixture(tmp_path)
    old_roster = existing.manager.require_state()[0].own_team().model_dump()
    world.post_behavior = "reject"
    review = actions.review("team-a", proposal["proposal_id"])
    receipt = actions.submit("team-a", proposal["proposal_id"], review["review_nonce"], True)
    assert receipt["status"] == "rejected" and receipt["retry_allowed"] is False
    assert len(world.posts) == 1
    assert existing.manager.require_state()[0].own_team().model_dump() == old_roster


def test_pending_waiver_preserves_ownership_and_blocks_repeated_approval(tmp_path):
    _, actions, existing, world, proposal, _ = live_fixture(tmp_path, waiver=True)
    review = actions.review("team-a", proposal["proposal_id"])
    receipt = actions.submit("team-a", proposal["proposal_id"], review["review_nonce"], True)
    assert receipt["status"] == "pending_waiver" and receipt["retry_allowed"] is False
    assert "109" not in existing.manager.require_state()[0].own_team().roster_ids
    assert len(world.posts) == 1
    with pytest.raises(DashboardActionError):
        actions.review("team-a", proposal["proposal_id"])
    assert len(world.posts) == 1
    with pytest.raises(DashboardActionError):
        actions.review("team-a", proposal["proposal_id"])
    assert len(world.posts) == 1


def test_config_change_between_review_and_submit_blocks_service_creation(tmp_path):
    _, actions, existing, world, proposal, instances = live_fixture(tmp_path)
    review = actions.review("team-a", proposal["proposal_id"])
    _, config, _, revision = existing.manager.require_state()
    config.automation.paused = True
    existing.manager.update_config(config.model_dump(mode="json"), revision)
    with pytest.raises(DashboardActionError):
        actions.submit("team-a", proposal["proposal_id"], review["review_nonce"], True)
    assert instances == [] and world.posts == []
