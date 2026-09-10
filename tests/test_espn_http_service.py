"""Exercise the actual season service against fictional HTTP state."""

from copy import deepcopy
from urllib.parse import parse_qs, urlsplit

import pytest

from fantasy_football_manager.espn_http_client import ESPNHTTPError
from fantasy_football_manager.espn_http_season import ESPNHTTPSeason
from fantasy_football_manager.espn_service import ESPNService
from fantasy_football_manager.models import ACTIONS, ManagerConfig
from test_espn_http_data import MEMBER, PRO_TEAMS_URL, fixture, pro_teams_fixture


pytestmark = pytest.mark.asyncio


class FakeESPN:
    """Keep raw response state separate from the manager's persisted snapshots."""

    def __init__(self):
        self.league, self.pool, _ = fixture()
        self.pro_teams = pro_teams_fixture()
        for team in self.league["teams"]:
            team["transactionCounter"].update(drops=0, matchupAcquisitionTotals={"1": 0})
        self.league["pendingTransactions"] = []
        self.history, self.posts, self.requests = [], [], []
        self.period = 1
        self.period_response = None
        self.before_post = None
        self.post_behavior = "execute"
        self.credential_calls = 0
        self.fail_on_credential_call = None
        self.fail_reads = False

    def credentials(self):
        self.credential_calls += 1
        if self.credential_calls == self.fail_on_credential_call:
            raise ValueError("The ESPN credential file is invalid.")
        return {"SWID": MEMBER, "espn_s2": "fictional-session"}

    def player(self, pid, **changes):
        for wrapper in self.pool["players"]:
            if wrapper["id"] == pid:
                wrapper["player"].update(deepcopy(changes))
        for team in self.league["teams"]:
            for entry in team["roster"]["entries"]:
                if entry["playerId"] == pid:
                    entry["playerPoolEntry"]["player"].update(deepcopy(changes))

    def projection(self, pid, points):
        raw = next(row["player"] for row in self.pool["players"] if row["id"] == pid)
        stats = deepcopy(raw["stats"])
        stats[1]["stats"] = {} if points is None else {"53": points}
        self.player(pid, stats=stats)

    def apply(self, transaction):
        entries = self.league["teams"][0]["roster"]["entries"]
        counter = self.league["teams"][0]["transactionCounter"]
        for item in transaction["items"]:
            pid = item["playerId"]
            if item["type"] == "LINEUP":
                entry = next(entry for entry in entries if entry["playerId"] == pid)
                assert entry["lineupSlotId"] == item["fromLineupSlotId"]
                entry["lineupSlotId"] = item["toLineupSlotId"]
            else:
                wrapper = next(row for row in self.pool["players"] if row["id"] == pid)
                if item["type"] == "ADD":
                    assert wrapper["onTeamId"] == 0
                    wrapper.update(onTeamId=1, status="ONTEAM")
                    entries.append({"playerId": pid, "lineupSlotId": 20, "playerPoolEntry": deepcopy(wrapper)})
                    counter["acquisitions"] += 1
                    counter["acquisitionBudgetSpent"] += transaction.get("bidAmount", 0)
                elif item["type"] == "DROP":
                    entries[:] = [entry for entry in entries if entry["playerId"] != pid]
                    wrapper.update(onTeamId=0, status="FREEAGENT")
                    counter["drops"] += 1
        transaction = deepcopy(transaction)
        transaction.update(status="EXECUTED", isPending=False)
        self.history.append(transaction)
        self.league["pendingTransactions"] = [row for row in self.league["pendingTransactions"]
                                               if row["id"] != transaction["id"]]

    async def request(self, url, *, payload=None, headers=None):
        self.requests.append((url, deepcopy(payload)))
        if payload is not None:
            if self.before_post:
                self.before_post(payload)
            self.posts.append(deepcopy(payload))
            transaction = {**deepcopy(payload), "id": f"receipt-{len(self.posts)}", "bidAmount": payload.get("bidAmount", 0),
                           "status": "EXECUTED", "isPending": False}
            if self.post_behavior == "pending":
                transaction.update(status="PENDING", isPending=True)
                self.league["pendingTransactions"].append(deepcopy(transaction))
            elif self.post_behavior == "reject":
                transaction["status"] = "FAILED_LINEUPLOCK"
            elif self.post_behavior == "no_effect":
                pass
            else:
                self.apply(transaction)
            if self.post_behavior == "apply_then_timeout":
                raise ESPNHTTPError("The response was lost.", submission_uncertain=True)
            return transaction
        if self.fail_reads:
            raise ESPNHTTPError("ESPN authentication is required.", status=401)
        query = parse_qs(urlsplit(url).query)
        if query.get("view") == ["proTeamSchedules_wl"]:
            assert url == PRO_TEAMS_URL
            return deepcopy(self.pro_teams)
        if query.get("view") == ["mStatus"]:
            return deepcopy(self.period_response or {"id": 123, "seasonId": 2026,
                            "status": {"transactionScoringPeriod": self.period, "finalScoringPeriod": 18}})
        week = int(query["scoringPeriodId"][0])
        if query.get("view") == ["kona_player_info"]:
            return {"players": deepcopy(self.pool["players"])}
        if query.get("view") == ["mTransactions2"]:
            return {"id": 123, "seasonId": 2026, "scoringPeriodId": week,
                    "transactions": deepcopy(self.history)}
        result = deepcopy(self.league)
        result["scoringPeriodId"] = week
        result["status"].update(latestScoringPeriod=self.period, transactionScoringPeriod=self.period)
        if "forTeamId" in query:
            result["teams"] = [team for team in result["teams"] if team["id"] == int(query["forTeamId"][0])]
        return result


async def case(tmp_path, *, world=None, automatic=("set_lineup",), limits=None, week=1, rollover=False):
    world = world or FakeESPN()
    adapter = ESPNHTTPSeason(tmp_path, week=week, client=world)
    service = ESPNService(tmp_path, browser=adapter, transport="http", auto_rollover=rollover)
    config = ManagerConfig(automation={"preset": "custom",
                           "actions": {action: "automatic" if action in automatic else "advisory" for action in ACTIONS}},
                           limits={"min_lineup_improvement": 1.5, **(limits or {})})
    service.manager.update_config(config.model_dump(mode="json"), 0)
    await service.connect(123, 1, 2026, phase="season", week=week)
    await service.sync()
    return service, adapter, world


def durable_rows(service):
    with service.manager.transaction() as db:
        return [dict(row) for row in db.execute("SELECT * FROM espn_http_proposals ORDER BY rowid")]


async def cycle(service):
    await service.sync()
    await service._season_step(*service.manager.require_state())


async def test_observation_reads_scoped_professional_schedule_and_refreshes_byes(tmp_path):
    service, _, world = await case(tmp_path)
    assert all(player.espn.bye_verified is True for player in service.manager.require_state()[0].players)
    assert sum(url == PRO_TEAMS_URL for url, _ in world.requests) == 2
    world.pro_teams["settings"]["proTeams"][1]["byeWeek"] = 1
    await service.sync()
    players = {player.id: player for player in service.manager.require_state()[0].players}
    assert players["101"].bye == 1 and players["-16001"].bye == 10
    assert sum(url == PRO_TEAMS_URL for url, _ in world.requests) == 3
    assert world.posts == []
    await service.close()


async def test_unknown_professional_schedule_blocks_new_lineup_submission(tmp_path):
    world = FakeESPN()
    world.pro_teams = None
    world.projection(103, 30)
    service, _, world = await case(tmp_path, world=world)
    with pytest.raises(ValueError, match="bye"):
        await service.prepare_lineup({"RB1": "103", "FLEX1": "102"})
    assert durable_rows(service) == [] and world.posts == []
    await service.close()


async def test_invalid_professional_schedule_releases_failed_connection(tmp_path):
    world = FakeESPN()
    world.pro_teams["settings"]["proTeams"].append({"id": 1, "byeWeek": 9})
    adapter = ESPNHTTPSeason(tmp_path, client=world)
    service = ESPNService(tmp_path, browser=adapter, transport="http")
    with pytest.raises(ValueError, match="duplicated"):
        await service.connect(123, 1, 2026, phase="season")
    assert not adapter.status()["connected"] and adapter._lease is None
    assert world.posts == []
    await service.close()


async def test_automatic_lineup_claim_precedes_one_post_and_fresh_roster_confirmation(tmp_path):
    world = FakeESPN()
    world.projection(103, 30)
    world.projection(102, 20)
    service, adapter, world = await case(tmp_path, world=world)

    def before_post(payload):
        rows = durable_rows(service)
        assert len(rows) == 1 and rows[0]["status"] == "awaiting_verification" and rows[0]["authorized_at"]
        assert service.manager.require_state()[0].own_team().lineup["RB1"] == "101"
        assert payload["type"] == "ROSTER"

    world.before_post = before_post
    await cycle(service)
    rows = durable_rows(service)
    assert len(world.posts) == 1 and rows[0]["status"] == "confirmed"
    assert service.manager.require_state()[0].own_team().lineup["RB1"] == "103"
    assert world.posts[0]["items"] == [
        {"playerId": 101, "type": "LINEUP", "fromLineupSlotId": 2, "toLineupSlotId": 20},
        {"playerId": 103, "type": "LINEUP", "fromLineupSlotId": 20, "toLineupSlotId": 2}]
    assert (await service.submit_lineup(rows[0]["id"]))["status"] == "confirmed"
    assert len(world.posts) == 1
    await service.close()
    assert adapter.status()["browser_started"] is False and not adapter.status()["connected"]


async def test_coverage_acquisition_and_start_are_two_confirmed_transactions(tmp_path):
    world = FakeESPN()
    world.projection(101, None)
    world.projection(109, 40)
    service, _, world = await case(tmp_path, world=world, automatic=("set_lineup", "free_agent_add", "drop_player"),
        limits={"coverage_repair_ids": ["101"], "coverage_repair_add_ids": ["109"], "allowed_drop_ids": ["103"]})
    await cycle(service)
    first = durable_rows(service)
    assert len(world.posts) == 1 and first[0]["action"] == "free_agent_add" and first[0]["status"] == "confirmed"
    snapshot = service.manager.require_state()[0]
    assert "109" in snapshot.own_team().roster_ids and "103" not in snapshot.own_team().roster_ids
    assert snapshot.own_team().lineup["RB1"] == "101"
    await cycle(service)
    rows = durable_rows(service)
    assert [row["action"] for row in rows] == ["free_agent_add", "set_lineup"]
    assert [row["status"] for row in rows] == ["confirmed", "confirmed"]
    assert len(world.posts) == 2 and rows[0]["id"] != rows[1]["id"]
    assert service.manager.require_state()[0].own_team().lineup["RB1"] == "109"
    await service.close()


async def test_waiver_acceptance_does_not_imply_ownership_or_allow_duplicate_submission(tmp_path):
    world = FakeESPN()
    world.projection(109, 40)
    next(row for row in world.pool["players"] if row["id"] == 109)["status"] = "WAIVERS"
    world.post_behavior = "pending"
    service, adapter, world = await case(tmp_path, world=world, automatic=("waiver_claim", "drop_player"),
                                        limits={"allowed_drop_ids": ["103"]}, rollover=True)
    proposal = await service.prepare_season_action("waiver_claim", {"player_id": "109", "drop_id": "103", "bid": 3})
    result = await service.submit_season_action(proposal["proposal_id"])
    assert result["status"] == "pending_waiver" and len(world.posts) == 1
    assert "109" not in service.manager.require_state()[0].own_team().roster_ids
    assert (await service.submit_season_action(proposal["proposal_id"]))["status"] == "pending_waiver"
    assert len(world.posts) == 1
    world.period = 2
    await service.sync()
    assert adapter.week == service.manager.require_state()[0].week == 1
    assert service.saved_connection()["week"] == 1
    world.apply(world.league["pendingTransactions"][0])
    await service.sync()
    assert service.http_actions.get(proposal["proposal_id"])["status"] == "confirmed"
    await service.sync()
    assert adapter.week == service.manager.require_state()[0].week == 2
    assert len(world.posts) == 1
    await service.close()


async def test_lost_response_is_reconciled_without_another_post(tmp_path):
    world = FakeESPN()
    world.projection(103, 30)
    world.post_behavior = "apply_then_timeout"
    service, _, world = await case(tmp_path, world=world)
    proposal = await service.prepare_lineup({"RB1": "103", "FLEX1": "102"})
    result = await service.submit_lineup(proposal["proposal_id"])
    assert result["status"] == "awaiting_verification" and result["retry_allowed"] is False
    assert len(world.posts) == 1
    await service.sync()
    assert service.http_actions.get(proposal["proposal_id"])["status"] == "confirmed"
    await service.submit_lineup(proposal["proposal_id"])
    assert len(world.posts) == 1
    await service.close()


async def test_http_success_without_roster_effect_remains_unresolved_and_blocks_rollover(tmp_path):
    world = FakeESPN()
    world.projection(103, 30)
    world.post_behavior = "no_effect"
    service, adapter, world = await case(tmp_path, world=world, rollover=True)
    proposal = await service.prepare_lineup({"RB1": "103", "FLEX1": "102"})
    result = await service.submit_lineup(proposal["proposal_id"])
    assert result["status"] == "awaiting_verification"
    world.period = 2
    await service.sync()
    assert adapter.week == 1 and service.manager.require_state()[0].week == 1
    await service.submit_lineup(proposal["proposal_id"])
    assert len(world.posts) == 1
    await service.close()


async def test_matching_failed_status_and_unchanged_roster_reject_without_retry(tmp_path):
    world = FakeESPN()
    world.projection(103, 30)
    world.post_behavior = "reject"
    service, _, world = await case(tmp_path, world=world)
    proposal = await service.prepare_lineup({"RB1": "103", "FLEX1": "102"})
    result = await service.submit_lineup(proposal["proposal_id"])
    assert result["status"] == "rejected"
    assert durable_rows(service)[0]["status"] == "rejected"
    assert service.manager.require_state()[0].own_team().lineup["RB1"] == "101"
    assert (await service.submit_lineup(proposal["proposal_id"]))["status"] == "rejected"
    assert len(world.posts) == 1
    await service.close()


@pytest.mark.parametrize("decision", [False, None, {"should_submit": True}])
async def test_preflight_requires_explicit_validator_authorization(tmp_path, decision):
    world = FakeESPN()
    world.projection(103, 30)
    service, adapter, world = await case(tmp_path, world=world)
    proposal = await service.prepare_lineup({"RB1": "103", "FLEX1": "102"})
    permit = service.http_actions.authorize(proposal["proposal_id"])
    assert permit["scope"] == "espn_http"
    adapter.permit_validator = lambda *_: decision
    with pytest.raises(ValueError, match="authorize"):
        await adapter.submit_action(permit)
    assert world.posts == []
    await service.close()


async def test_credential_failure_after_authorization_never_posts(tmp_path):
    world = FakeESPN()
    world.projection(103, 30)
    service, _, world = await case(tmp_path, world=world)
    proposal = await service.prepare_lineup({"RB1": "103", "FLEX1": "102"})
    world.fail_on_credential_call = world.credential_calls + 2
    result = await service.submit_lineup(proposal["proposal_id"])
    assert result["status"] == "not_submitted" and world.posts == []
    assert result["submission_phase"] == "preflight" and result["should_submit"] is False
    assert durable_rows(service)[0]["status"] == "not_submitted"
    assert (await service.submit_lineup(proposal["proposal_id"]))["status"] == "not_submitted"
    assert world.posts == []
    await service.close()


async def test_failed_read_connection_is_closed_without_browser_or_posts(tmp_path):
    world = FakeESPN()
    world.fail_reads = True
    adapter = ESPNHTTPSeason(tmp_path, client=world)
    service = ESPNService(tmp_path, browser=adapter, transport="http")
    with pytest.raises(ESPNHTTPError):
        await service.connect(123, 1, 2026, phase="season")
    assert adapter.status() == {"connected": False, "transport": "http", "browser_started": False,
                               "week": 1, "authenticated": False}
    assert world.posts == []
    await service.close()


async def test_shared_session_prevents_same_team_control_across_separate_manager_databases(tmp_path):
    first_world, second_world = FakeESPN(), FakeESPN()
    first_world.credential_file = second_world.credential_file = tmp_path / "private-session" / "session.json"
    first_adapter = ESPNHTTPSeason(tmp_path / "first", client=first_world)
    second_adapter = ESPNHTTPSeason(tmp_path / "second", client=second_world)
    first = ESPNService(tmp_path / "first", browser=first_adapter, transport="http")
    second = ESPNService(tmp_path / "second", browser=second_adapter, transport="http")
    try:
        await first.connect(123, 1, 2026, phase="season")
        with pytest.raises(ValueError, match="Another HTTP service owns"):
            await second.connect(123, 1, 2026, phase="season")
        assert second_world.requests == [] and not second_adapter.status()["connected"]
        assert first_adapter.status()["connected"]
        await first.close()
        assert (await second.connect(123, 1, 2026, phase="season"))["ready"] is True
        assert first_world.posts == second_world.posts == []
    finally:
        await first.close()
        await second.close()


async def test_shared_session_allows_other_team_and_releases_lease_after_failed_read(tmp_path):
    first_world, second_world = FakeESPN(), FakeESPN()
    first_world.credential_file = second_world.credential_file = tmp_path / "private-session" / "session.json"
    second_world.league["teams"][1]["owners"] = [MEMBER]
    second_world.fail_reads = True
    first_adapter = ESPNHTTPSeason(tmp_path / "first", client=first_world)
    second_adapter = ESPNHTTPSeason(tmp_path / "second", client=second_world)
    first = ESPNService(tmp_path / "first", browser=first_adapter, transport="http")
    second = ESPNService(tmp_path / "second", browser=second_adapter, transport="http")
    try:
        await first.connect(123, 1, 2026, phase="season")
        with pytest.raises(ESPNHTTPError):
            await second.connect(123, 2, 2026, phase="season")
        assert not second_adapter.status()["connected"]
        assert second_adapter._lease is None
        second_world.fail_reads = False
        assert (await second.connect(123, 2, 2026, phase="season"))["ready"] is True
        assert first_adapter.status()["connected"] and second_adapter.status()["connected"]
        assert first_adapter.status()["browser_started"] is second_adapter.status()["browser_started"] is False
        assert first_world.posts == second_world.posts == []
    finally:
        await first.close()
        await second.close()


@pytest.mark.parametrize("bad_period", ["backward", "wrong_league", "missing", "boolean"])
async def test_rollover_rejects_backward_or_unverified_current_period(tmp_path, bad_period):
    world = FakeESPN()
    world.period = 2
    service, adapter, world = await case(tmp_path, world=world, week=2, rollover=True)
    if bad_period == "backward":
        world.period = 1
    else:
        world.period_response = {"id": 999 if bad_period == "wrong_league" else 123, "seasonId": 2026,
                                "status": {"finalScoringPeriod": 18}}
        if bad_period == "boolean":
            world.period_response["status"]["transactionScoringPeriod"] = True
    with pytest.raises(ValueError):
        await service.sync()
    assert adapter.week == service.manager.require_state()[0].week == 2 and world.posts == []
    await service.close()
