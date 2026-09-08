"""Monitor tests use synthetic state and bounded simulation stubs."""

from datetime import datetime, timedelta, timezone
import threading

import pytest

from fantasy_football_manager import legacy_engine, runtime
from fantasy_football_manager.models import LeagueSnapshot, ManagerConfig


class ManagerStub:
    def __init__(self, complete=False):
        now = datetime.now(timezone.utc)
        self.snapshot = LeagueSnapshot.model_validate({
            "league_id": "synthetic-league", "team_id": "team-1", "season": 2026, "phase": "draft",
            "source": {"provider": "synthetic", "synthetic": True, "observed_at": now,
                       "projections_observed_at": now},
            "rules": {"teams": 2, "slot": 1, "rounds": 1, "starters": {}, "bench": 1},
            "players": [{"id": "p1", "name": "Synthetic player 1", "position": "RB", "projection": 100},
                        {"id": "p2", "name": "Synthetic player 2", "position": "WR", "projection": 90}],
            "teams": [{"id": "team-1", "name": "Synthetic team 1", "slot": 1, "roster_ids": ["p1"] if complete else []},
                      {"id": "team-2", "name": "Synthetic team 2", "slot": 2}],
            "picks": [{"pick_no": 1, "player_id": "p1", "slot": 1}] if complete else []})
        self.config = ManagerConfig()
        self.revision = self.config_revision = 1
        self.reads = 0

    def state(self):
        return self.snapshot, self.config, self.revision, self.config_revision

    def require_state(self):
        self.reads += 1
        return self.state()


class ControlledEvent:
    def __init__(self, steps, callback=None):
        self.steps = steps
        self.callback = callback
        self.waits = 0
        self.stopped = False

    def is_set(self):
        return self.stopped

    def set(self):
        self.stopped = True

    def wait(self, timeout):
        self.waits += 1
        if self.callback:
            self.callback(self.waits)
        if self.waits >= self.steps:
            self.set()
        return self.stopped


def batch(seed, trials=4, fingerprint="same", status="ready"):
    row = {"id": "p1", "score": float(seed), "score_sum": seed*trials,
           "score_sq_sum": seed*seed*trials, "simulation_count": trials,
           "availability_count": trials, "survival_count": trials // 2,
           "trial_count": trials, "availability_at_pick": 1, "survival_next_pick": .5,
           "adp": 1, "reason": "Fills an open starter position."}
    return {"trials": trials, "recommendations": [row] if trials else [], "current_pick": 1,
            "my_next_pick": 1, "following_pick": 4, "available_count": 2,
            "completed": False, "analysis_fingerprint": fingerprint, "status": status}


def test_monitor_aggregates_sums_and_variance_for_identical_inputs(monkeypatch):
    manager = ManagerStub()
    monitor = runtime.DraftMonitor(manager)
    monitor.stop_event = ControlledEvent(2)
    monkeypatch.setattr(runtime, "recommend_draft", lambda s, c, n, seed: batch(seed, n))
    monitor._run(1, 4)
    result = monitor.get()
    assert result["completed_trials"] == result["current_state_trials"] == 8
    assert result["latest"]["batch_count"] == 2
    assert result["latest"]["first_seed"] == 1 and result["latest"]["last_seed"] == 2
    row = result["latest"]["result"]["recommendations"][0]
    assert row["score"] == 1.5 and row["score_sum"] == 12
    assert row["score_se"] == pytest.approx((.25 / 8) ** .5)
    assert row["availability_at_pick"] == 1 and row["survival_next_pick"] == .5
    result["latest"]["result"]["recommendations"].clear()
    assert monitor.get()["latest"]["result"]["recommendations"]


@pytest.mark.parametrize("field", ["revision", "config_revision"])
def test_changed_revision_discards_inflight_batch_and_resets_aggregate(monkeypatch, field):
    manager = ManagerStub()
    monitor = runtime.DraftMonitor(manager)
    monitor.stop_event = ControlledEvent(3)

    def calculate(snapshot, config, trials, seed):
        if seed == 2:
            setattr(manager, field, 2)
        return batch(seed, trials, fingerprint=str(getattr(manager, field)))

    monkeypatch.setattr(runtime, "recommend_draft", calculate)
    monitor._run(1, 4)
    result = monitor.get()
    assert result["completed_trials"] == 12 and result["current_state_trials"] == 4
    assert result["discarded_batches"] == 1 and result["discarded_trials"] == 4
    assert result["latest"]["result"]["recommendations"][0]["score"] == 3
    assert result["latest"][field] == 2


@pytest.mark.parametrize("state", ["paused", "stale", "incomplete"])
def test_monitor_waits_without_simulation_for_unusable_state(monkeypatch, state):
    manager = ManagerStub()
    if state == "paused":
        manager.config.automation.paused = True
    elif state == "stale":
        manager.snapshot.source.observed_at -= timedelta(seconds=60)
    else:
        manager.snapshot.source.complete = False
    monitor = runtime.DraftMonitor(manager)
    statuses = []
    monitor.stop_event = ControlledEvent(1, lambda _: statuses.append(monitor.status))
    monkeypatch.setattr(runtime, "recommend_draft", lambda *a: pytest.fail("Unusable state ran a simulation."))
    monitor._run(1, 4)
    assert statuses == [{"paused": "paused", "stale": "waiting_for_fresh_snapshot", "incomplete": "waiting_for_complete_snapshot"}[state]]
    assert monitor.completed_trials == 0 and monitor.get()["latest"] is None


def test_snapshot_that_expires_during_batch_cannot_be_published(monkeypatch):
    manager = ManagerStub()
    monitor = runtime.DraftMonitor(manager)
    monitor.stop_event = ControlledEvent(1)

    def calculate(snapshot, config, trials, seed):
        manager.snapshot.source.observed_at -= timedelta(seconds=60)
        return batch(seed, trials)

    monkeypatch.setattr(runtime, "recommend_draft", calculate)
    monitor._run(1, 4)
    result = monitor.get()
    assert result["completed_trials"] == result["discarded_trials"] == 4
    assert not result["current"] and result["latest"] is None


def test_monitor_finishes_after_own_roster_before_league_end(monkeypatch):
    manager = ManagerStub(complete=True)
    monitor = runtime.DraftMonitor(manager)
    monitor.stop_event = ControlledEvent(1)
    monkeypatch.setattr(legacy_engine, "run_batch", lambda *a, **kw: pytest.fail("A complete roster ran Monte Carlo."))
    monitor._run(1, 4)
    result = monitor.get()
    assert result["status"] == "complete" and result["completed_trials"] == 0
    assert result["latest"]["result"]["status"] == "roster_complete"
    assert not result["latest"]["result"]["draft_complete"]
    assert result["latest"]["batch_count"] == 0
    assert monitor.stop_event.waits == 0


def test_blocked_result_does_not_repeat_zero_work_batches(monkeypatch):
    monitor = runtime.DraftMonitor(ManagerStub())
    monitor.stop_event = ControlledEvent(3)
    calls = []

    def calculate(snapshot, config, trials, seed):
        calls.append(seed)
        return batch(seed, 0, status="missing_projections")

    monkeypatch.setattr(runtime, "recommend_draft", calculate)
    monitor._run(1, 4)
    assert calls == [1] and monitor.completed_trials == 0
    assert monitor.get()["latest"]["batch_count"] == 0


def test_get_hides_cached_result_after_input_change(monkeypatch):
    manager = ManagerStub()
    monitor = runtime.DraftMonitor(manager)
    monitor.stop_event = ControlledEvent(1)
    monkeypatch.setattr(runtime, "recommend_draft", lambda s, c, n, seed: batch(seed, n))
    monitor._run(1, 4)
    manager.config_revision += 1
    result = monitor.get()
    assert result["completed_trials"] == 4 and result["current_state_trials"] == 0
    assert not result["current"] and result["latest"] is None


def test_stop_during_batch_joins_without_lock_deadlock_or_another_state_poll(monkeypatch):
    manager = ManagerStub()
    monitor = runtime.DraftMonitor(manager)
    entered, release, stopped = threading.Event(), threading.Event(), threading.Event()

    def calculate(snapshot, config, trials, seed):
        entered.set()
        assert release.wait(2)
        return batch(seed, trials)

    monkeypatch.setattr(runtime, "recommend_draft", calculate)
    monitor.start(trials=4)
    assert entered.wait(1)
    reads = manager.reads
    stopper = threading.Thread(target=lambda: (monitor.stop(), stopped.set()))
    stopper.start()
    assert monitor.stop_event.wait(1)
    release.set()
    assert stopped.wait(2)
    stopper.join(1)
    assert not monitor.thread.is_alive() and monitor.status == "stopped"
    assert manager.reads == reads
    assert monitor.completed_trials == monitor.discarded_trials == 4


def test_stop_wait_is_bounded_when_worker_has_not_finished():
    class UnfinishedThread:
        def is_alive(self):
            return True

        def join(self, timeout):
            assert timeout == 5

    monitor = runtime.DraftMonitor(ManagerStub())
    monitor.thread = UnfinishedThread()
    result = monitor.stop()
    assert result["status"] == "stopping" and result["running"]


def test_phase_change_stops_without_a_simulation(monkeypatch):
    manager = ManagerStub()
    manager.snapshot.phase = "season"
    monitor = runtime.DraftMonitor(manager)
    monkeypatch.setattr(runtime, "recommend_draft", lambda *a: pytest.fail("Season state ran a draft simulation."))
    monitor._run(1, 4)
    assert monitor.status == "phase_changed" and monitor.completed_trials == 0
