from __future__ import annotations

from typing import Any

from control_plane_client import ControlPlaneReporter


class ControlPlaneRun:
    """Best-effort lifecycle adapter for a single frozen watcher invocation."""

    def __init__(self, reporter: ControlPlaneReporter | None = None, run_id: str | None = None) -> None:
        self.reporter = reporter
        self.run_id = run_id

    @classmethod
    def begin(
        cls,
        prefix: str,
        config_revision: int | None,
        *,
        scheduler_job_id: str,
        trigger: str = "scheduled",
    ) -> "ControlPlaneRun":
        if config_revision is None:
            return cls()
        try:
            reporter = ControlPlaneReporter.from_environment(prefix)
            if reporter is None:
                return cls()
            return cls(
                reporter,
                reporter.start_run(
                    config_revision,
                    scheduler_job_id=scheduler_job_id,
                    trigger=trigger,
                ),
            )
        except Exception:
            return cls()

    def event(
        self,
        event_id: str,
        *,
        level: str,
        phase: str,
        event_type: str,
        message: str,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        if self.reporter is None or self.run_id is None:
            return
        try:
            self.reporter.event(
                self.run_id,
                event_id,
                level=level,
                phase=phase,
                event_type=event_type,
                message=message,
                attributes=attributes,
                flush=False,
            )
        except Exception:
            pass

    def finish(self, status: str, error: str | None = None) -> None:
        if self.reporter is None or self.run_id is None:
            return
        try:
            self.reporter.finish(self.run_id, status, error)
        except Exception:
            pass
