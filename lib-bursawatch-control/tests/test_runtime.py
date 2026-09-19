from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))

from control_plane_runtime import ControlPlaneRun  # noqa: E402


class FakeReporter:
    def __init__(self) -> None:
        self.started = []
        self.events = []
        self.finished = []

    def start_run(self, revision, *, scheduler_job_id, trigger):
        self.started.append((revision, scheduler_job_id, trigger))
        return "run-1"

    def event(self, run_id, event_id, **kwargs):
        self.events.append((run_id, event_id, kwargs))

    def finish(self, run_id, status, error=None):
        self.finished.append((run_id, status, error))


def test_static_mode_does_not_create_a_control_plane_run():
    run = ControlPlaneRun.begin(
        "X_POST_WATCH",
        None,
        scheduler_job_id="x-post-source",
    )

    assert run.reporter is None
    assert run.run_id is None


def test_live_mode_reports_events_best_effort(monkeypatch):
    fake = FakeReporter()
    monkeypatch.setattr(
        "control_plane_runtime.ControlPlaneReporter.from_environment",
        lambda prefix: fake,
    )

    run = ControlPlaneRun.begin(
        "X_POST_WATCH",
        9,
        scheduler_job_id="x-post-source",
        trigger="scheduled",
    )
    run.event(
        "run-completed",
        level="info",
        phase="lifecycle",
        event_type="run.completed",
        message="completed",
        attributes={"queued": 1},
    )
    run.finish("ok")

    assert fake.started == [(9, "x-post-source", "scheduled")]
    assert fake.events[0][0:2] == ("run-1", "run-completed")
    assert fake.events[0][2]["flush"] is False
    assert fake.finished == [("run-1", "ok", None)]
