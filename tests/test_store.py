from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from fantasy_football_manager.demo import make_demo
from fantasy_football_manager.models import ManagerConfig
from fantasy_football_manager.policy import PolicyError
from fantasy_football_manager.season import recommend_lineup
from fantasy_football_manager.store import Manager


@pytest.fixture
def manager(tmp_path):
    manager = Manager(tmp_path)
    manager.import_snapshot(make_demo().model_dump(mode="json"))
    config = ManagerConfig()
    config.automation.preset = "review"
    manager.update_config(config.model_dump(mode="json"), 0)
    return manager


def proposal(manager):
    snapshot, config, _, _ = manager.require_state()
    result = recommend_lineup(snapshot, config)
    return manager.prepare("set_lineup", {"lineup": result["lineup"]})


def test_review_requires_exact_proposal_confirmation_and_replay_is_idempotent(manager):
    prepared = proposal(manager)
    with pytest.raises(PolicyError, match="confirmation"):
        manager.execute(prepared["proposal_id"])
    assert manager.state()[2] == 1
    result = manager.execute(prepared["proposal_id"], True)
    assert result["revision"] == 2
    assert manager.execute(prepared["proposal_id"], True)["idempotent_replay"]
    assert manager.state()[2] == 2
    assert len([row for row in manager.history() if row["event"] == "demo_action_executed"]) == 1


def test_concurrent_execution_commits_once(manager):
    prepared = proposal(manager)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: manager.execute(prepared["proposal_id"], True), range(2)))
    assert sorted(item["idempotent_replay"] for item in results) == [False, True]
    assert manager.state()[2] == 2


def test_changed_config_invalidates_prepared_action(manager):
    prepared = proposal(manager)
    _, config, _, revision = manager.state()
    config.automation.paused = True
    manager.update_config(config.model_dump(mode="json"), revision)
    with pytest.raises(PolicyError, match="changed"):
        manager.execute(prepared["proposal_id"], True)
    assert manager.state()[2] == 1


def test_changed_snapshot_invalidates_prepared_action(manager):
    prepared = proposal(manager)
    snapshot, _, revision, _ = manager.state()
    snapshot.source.observed_at = datetime.now(timezone.utc)
    manager.import_snapshot(snapshot.model_dump(mode="json"), revision)
    with pytest.raises(PolicyError, match="changed"):
        manager.execute(prepared["proposal_id"], True)


def test_import_requires_revision_and_rejects_older_observation(manager):
    snapshot, _, revision, _ = manager.state()
    with pytest.raises(ValueError, match="conflict"):
        manager.import_snapshot(snapshot.model_dump(mode="json"))
    snapshot.source.observed_at -= timedelta(seconds=1)
    with pytest.raises(ValueError, match="older"):
        manager.import_snapshot(snapshot.model_dump(mode="json"), revision)
    assert manager.state()[2] == revision


def test_scope_change_resets_permissions_and_limits(manager):
    old, _, revision, config_revision = manager.state()
    old.league_id = "different-synthetic-league"
    result = manager.import_snapshot(old.model_dump(mode="json"), revision)
    assert result["config_reset"]
    assert manager.state()[1].automation.preset == "advisory"
    assert manager.state()[3] == config_revision + 1


def test_database_reopens_with_state_and_audit(manager):
    second = Manager(manager.data_dir)
    assert second.state()[0] == manager.state()[0]
    assert len(second.history()) == 2


def test_no_real_adapter_can_be_enabled_by_config(manager):
    snapshot, config, revision, config_revision = manager.state()
    snapshot.source.synthetic = False
    snapshot.source.provider = "imported-espn"
    snapshot.source.observed_at = datetime.now(timezone.utc)
    manager.import_snapshot(snapshot.model_dump(mode="json"), revision)
    config.automation.preset = "bounded_automation"
    manager.update_config(config.model_dump(mode="json"), config_revision)
    with pytest.raises(PolicyError, match="Live provider writes"):
        proposal(manager)


def test_automatic_demo_pick_checks_turn_and_protects_history(tmp_path):
    manager = Manager(tmp_path)
    snapshot = make_demo("draft")
    manager.import_snapshot(snapshot.model_dump(mode="json"))
    config = ManagerConfig()
    config.automation.preset = "bounded_automation"
    manager.update_config(config.model_dump(mode="json"), 0)
    first = manager.prepare("draft_pick", {"player_id": "demo-wr-001"})
    result = manager.execute(first["proposal_id"])
    assert result["status"] == "executed"
    assert manager.state()[0].own_team().roster_ids == ["demo-wr-001"]
    with pytest.raises(PolicyError, match="turn"):
        manager.prepare("draft_pick", {"player_id": "demo-rb-001"})
    snapshot.source.observed_at = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="roll back"):
        manager.import_snapshot(snapshot.model_dump(mode="json"), 2)


def test_acquisition_is_atomic_and_spending_counts_once(manager):
    snapshot, config, revision, config_revision = manager.state()
    player = next(p for p in snapshot.players if p.id == "demo-wr-100")
    player.weekly_projection = 50
    player.weekly_floor = 35
    player.weekly_ceiling = 65
    snapshot.source.observed_at = datetime.now(timezone.utc)
    manager.import_snapshot(snapshot.model_dump(mode="json"), revision)
    config.limits.allowed_drop_ids = ["demo-qb-015"]
    manager.update_config(config.model_dump(mode="json"), config_revision)
    prepared = manager.prepare("waiver_claim", {"player_id": player.id, "drop_id": "demo-qb-015", "bid": 7})
    manager.execute(prepared["proposal_id"], True)
    manager.execute(prepared["proposal_id"], True)
    updated = manager.state()[0]
    assert len(updated.own_team().roster_ids) == 14
    assert "demo-qb-015" not in updated.own_team().roster_ids
    assert player.id in updated.own_team().roster_ids
    assert updated.budget.balance == 93
    assert updated.budget.spent_week == 7
    assert updated.budget.spent_season == 7
    assert updated.budget.roster_moves_week == 1


def test_combined_acquisition_requires_drop_permission(manager):
    _, config, _, revision = manager.state()
    config.automation.preset = "custom"
    config.automation.actions["waiver_claim"] = "automatic"
    config.limits.allowed_drop_ids = ["demo-qb-015"]
    manager.update_config(config.model_dump(mode="json"), revision)
    with pytest.raises(PolicyError, match="Every part"):
        manager.prepare("waiver_claim", {"player_id": "demo-wr-100", "drop_id": "demo-qb-015"})
