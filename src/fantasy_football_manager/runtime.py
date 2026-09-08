"""Repeated simulation batches for the latest imported draft state."""

import copy
import math
import threading
from datetime import datetime, timezone

from .draft import recommend_draft
from .legacy_engine import merge_batches


class DraftMonitor:
    def __init__(self, manager):
        self.manager = manager
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = None
        self.result = None
        self.status = "stopped"
        self.completed_trials = 0
        self.discarded_batches = 0
        self.discarded_trials = 0
        self.error = None

    def start(self, interval_seconds=2, trials=40):
        if (type(interval_seconds) not in {int, float} or not math.isfinite(interval_seconds)
                or not 1 <= interval_seconds <= 60 or type(trials) is not int or not 1 <= trials <= 500):
            raise ValueError("Use an interval from 1 to 60 seconds and 1 to 500 trials.")
        snapshot, config, _, _ = self.manager.require_state()
        if snapshot.phase != "draft":
            raise ValueError("The draft monitor requires a draft snapshot.")
        if trials > config.limits.batch_trials:
            raise ValueError("Requested trials exceed the configured batch limit.")
        with self.lock:
            if self.thread is not None and self.thread.is_alive():
                raise ValueError("A draft monitor is already active.")
            self.stop_event.clear()
            self.status, self.result, self.error = "starting", None, None
            self.completed_trials = self.discarded_batches = self.discarded_trials = 0
            self.thread = threading.Thread(target=self._run, args=(interval_seconds, trials), daemon=True,
                                           name="fantasy-draft-monitor")
            self.thread.start()
        return self.get()

    def _run(self, interval_seconds, trials):
        seed = 1
        active_revision = None
        try:
            while not self.stop_event.is_set():
                snapshot, config, revision, config_revision = self.manager.require_state()
                state_key = revision, config_revision
                with self.lock:
                    if state_key != active_revision:
                        self.result = None
                        active_revision = state_key
                if snapshot.phase != "draft":
                    with self.lock:
                        self.result, self.status = None, "phase_changed"
                    return
                own_complete = len(snapshot.own_team().roster_ids) >= snapshot.rules.rounds
                waiting = ("paused" if config.automation.paused else
                           "waiting_for_complete_snapshot" if not snapshot.source.complete else
                           "waiting_for_fresh_snapshot" if snapshot.age_seconds() > config.limits.max_draft_age_seconds else None)
                if waiting and not own_complete:
                    with self.lock:
                        self.result, self.status = None, waiting
                else:
                    with self.lock:
                        # A blocked result needs changed inputs, not another identical batch.
                        repeat = self.result is not None and self.result["result"].get("status") != "ready"
                        if not repeat:
                            self.status = "simulating"
                    if repeat:
                        self.stop_event.wait(interval_seconds)
                        continue
                    batch = recommend_draft(snapshot, config, min(trials, config.limits.batch_trials), seed)
                    batch_seed = seed
                    seed += 1
                    work = batch.get("trials", 0)
                    with self.lock:
                        self.completed_trials += work
                    # Stop before another state read when shutdown occurs during a batch.
                    if self.stop_event.is_set():
                        with self.lock:
                            self.discarded_batches += int(work > 0)
                            self.discarded_trials += work
                            self.status = "stopped"
                        return
                    latest, latest_config, latest_revision, latest_config_revision = self.manager.require_state()
                    changed = state_key != (latest_revision, latest_config_revision)
                    expired = latest.age_seconds() > latest_config.limits.max_draft_age_seconds
                    unusable = latest_config.automation.paused or not latest.source.complete or latest.phase != "draft" or expired
                    with self.lock:
                        if self.stop_event.is_set():
                            self.discarded_batches += int(work > 0)
                            self.discarded_trials += work
                            self.status = "stopped"
                            return
                        if changed or (unusable and not own_complete):
                            self.discarded_batches += int(work > 0)
                            self.discarded_trials += work
                            self.result = None
                            self.status = ("state_changed" if changed else "paused" if latest_config.automation.paused
                                           else "waiting_for_complete_snapshot" if not latest.source.complete
                                           else "waiting_for_fresh_snapshot")
                        else:
                            previous = self.result
                            aggregate = merge_batches(previous["result"] if previous else None, batch)
                            count = (previous["batch_count"] if previous else 0) + int(work > 0)
                            self.result = {"revision": revision, "config_revision": config_revision,
                                           "computed_at": datetime.now(timezone.utc).isoformat(), "result": aggregate,
                                           "batch_count": count, "last_batch_trials": work,
                                           "first_seed": previous["first_seed"] if previous else batch_seed,
                                           "last_seed": batch_seed}
                            self.status = "complete" if batch.get("completed") else "waiting" if work else batch["status"]
                            if batch.get("completed"):
                                return
                self.stop_event.wait(interval_seconds)
            with self.lock:
                self.status = "stopped"
        except Exception as exc:
            with self.lock:
                self.result = None
                self.status, self.error = "error", str(exc)

    def get(self):
        snapshot, config, revision, config_revision = self.manager.state()
        with self.lock:
            current = bool(self.result is not None and
                           (self.result["revision"], self.result["config_revision"]) == (revision, config_revision)
                           and snapshot is not None and snapshot.phase == "draft" and snapshot.source.complete
                           and snapshot.age_seconds() <= config.limits.max_draft_age_seconds
                           and not config.automation.paused)
            return {"status": self.status, "running": self.thread is not None and self.thread.is_alive(),
                    "current": current, "completed_trials": self.completed_trials,
                    "current_state_trials": self.result["result"].get("trials", 0) if current else 0,
                    "discarded_batches": self.discarded_batches, "discarded_trials": self.discarded_trials,
                    "error": self.error, "latest": copy.deepcopy(self.result) if current else None,
                    "data_feed": "imported_snapshots", "live_browser_monitoring": False,
                    "counter_scope": "Completed trials include all executed trials in this monitor session. Current state trials use matching inputs only.",
                    "note": "Each batch uses the latest imported snapshot. This worker does not read a browser or submit picks."}

    def stop(self, wait=True):
        """Signal shutdown. Wait at most five seconds for the current batch."""
        self.stop_event.set()
        with self.lock:
            thread = self.thread
            alive = thread is not None and thread.is_alive()
            self.status = "stopping" if alive else "stopped"
        if wait and alive and thread is not threading.current_thread():
            thread.join(timeout=5)
            with self.lock:
                self.status = "stopping" if thread.is_alive() else "stopped"
        return self.get()
