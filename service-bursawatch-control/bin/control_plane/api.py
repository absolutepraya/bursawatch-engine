from __future__ import annotations

from datetime import datetime
import json
import os
from typing import Any, Callable, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from .auth import Authenticator, AuthenticationError, Principal, StaticTokenAuth, auth_from_environment
from .contract import ConfigSnapshot, ContractError, canonical_json_bytes, validate_watcher_id
from .store import EventRecord, InMemoryStore, PostgresStore, RunRecord, SchedulerJobRecord, Store
from .validators import validators_from_environment


class ConfigWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config_version: int = Field(ge=1)
    config: dict[str, Any]


class RunStart(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str | None = Field(default=None, min_length=1, max_length=128)
    watcher_id: str
    config_revision: int = Field(ge=1)
    scheduler_job_id: str | None = None
    trigger: str = "scheduled"


class RunEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=128)
    occurred_at: str
    level: Literal["debug", "info", "warning", "error", "fatal"]
    phase: str = Field(min_length=1, max_length=64)
    event_type: str = Field(min_length=1, max_length=128)
    message: str = Field(max_length=500)
    attributes: dict[str, Any] = Field(default_factory=dict)


class RunFinish(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "degraded", "failed", "blocked"]
    error: str | None = Field(default=None, max_length=500)


class ScheduleWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool
    interval_seconds: int = Field(ge=60, le=86_400)
    timezone: str = Field(min_length=1, max_length=64)


def _snapshot_response(snapshot: ConfigSnapshot) -> dict[str, Any]:
    return snapshot.to_dict()


def _run_response(run: RunRecord) -> dict[str, Any]:
    return {
        "run_id": run.run_id,
        "watcher_id": run.watcher_id,
        "scheduler_job_id": run.scheduler_job_id,
        "trigger": run.trigger,
        "config_revision": run.config_revision,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "status": run.status,
        "error": run.error,
    }


def _event_response(event: EventRecord) -> dict[str, Any]:
    return {
        "run_id": event.run_id,
        "event_id": event.event_id,
        "occurred_at": event.occurred_at,
        "level": event.level,
        "phase": event.phase,
        "event_type": event.event_type,
        "message": event.message,
        "attributes": event.attributes,
    }


def _job_response(job: SchedulerJobRecord) -> dict[str, Any]:
    schedule = job.schedule.to_dict() if job.schedule else None
    effective = bool(
        job.schedule
        and job.reconciliation_status == "applied"
        and job.applied_revision == job.schedule.revision
    )
    return {
        "job_id": job.job_id,
        "watcher_id": job.watcher_id,
        "display_name": job.display_name,
        "runtime_job_key": job.runtime_job_key,
        "schedule_kind": job.schedule_kind,
        "min_interval_seconds": job.min_interval_seconds,
        "max_interval_seconds": job.max_interval_seconds,
        "schedule": schedule,
        "reconciliation": {
            "status": job.reconciliation_status,
            "applied_revision": job.applied_revision,
            "effective": effective,
        },
    }


def create_app(
    store: Store | None = None,
    auth: Authenticator | None = None,
    validators: dict[str, Callable[[dict[str, Any]], None]] | None = None,
    allowed_origins: list[str] | None = None,
) -> FastAPI:
    store = store or InMemoryStore()
    auth = auth or StaticTokenAuth.from_environment()
    validators = validators or {}
    app = FastAPI(title="Bursawatch Control Plane", version="1.0.0")
    if allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_credentials=True,
            allow_methods=["GET", "PUT", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
        )

    def principal(authorization: str | None = Header(default=None)) -> Principal:
        try:
            return auth.authenticate(authorization)
        except AuthenticationError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    def machine_or_admin(current: Principal = Depends(principal)) -> Principal:
        if current.kind not in {"machine", "admin"}:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient role")
        return current

    def admin_only(current: Principal = Depends(principal)) -> Principal:
        if current.kind != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin role required")
        return current

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/watchers")
    def list_watchers(_current: Principal = Depends(machine_or_admin)) -> list[dict[str, Any]]:
        return [
            {
                "watcher_id": watcher.watcher_id,
                "display_name": watcher.display_name,
                "current_revision": watcher.current_revision,
                "updated_at": watcher.updated_at,
            }
            for watcher in store.list_watchers()
        ]

    @app.get("/v1/watchers/{watcher_id}/config")
    def get_config(watcher_id: str, _current: Principal = Depends(machine_or_admin)) -> dict[str, Any]:
        try:
            validate_watcher_id(watcher_id)
            return _snapshot_response(store.get_config(watcher_id))
        except (ContractError, KeyError) as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="watcher config not found") from exc

    @app.get("/v1/watchers/{watcher_id}/runs")
    def list_runs(
        watcher_id: str,
        limit: int = Query(default=50, ge=1, le=200),
        _current: Principal = Depends(machine_or_admin),
    ) -> list[dict[str, Any]]:
        try:
            validate_watcher_id(watcher_id)
            return [_run_response(run) for run in store.list_runs(watcher_id, limit)]
        except ContractError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    @app.get("/v1/watchers/{watcher_id}/jobs")
    def list_jobs(
        watcher_id: str,
        _current: Principal = Depends(machine_or_admin),
    ) -> list[dict[str, Any]]:
        try:
            validate_watcher_id(watcher_id)
            return [_job_response(job) for job in store.list_jobs(watcher_id)]
        except ContractError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    @app.get("/v1/jobs/{job_id}/schedule")
    def get_schedule(job_id: str, _current: Principal = Depends(machine_or_admin)) -> dict[str, Any]:
        try:
            return _job_response(store.get_job(job_id))
        except (ContractError, KeyError) as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="scheduler job not found") from exc

    @app.get("/v1/runs/{run_id}/events")
    def list_events(
        run_id: str,
        limit: int = Query(default=500, ge=1, le=1000),
        _current: Principal = Depends(machine_or_admin),
    ) -> list[dict[str, Any]]:
        return [_event_response(event) for event in store.list_events(run_id, limit)]

    @app.put("/v1/watchers/{watcher_id}/config")
    def put_config(
        watcher_id: str,
        payload: ConfigWrite,
        current: Principal = Depends(admin_only),
    ) -> dict[str, Any]:
        try:
            validate_watcher_id(watcher_id)
            validator = validators[watcher_id]
        except (ContractError, KeyError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="no validator registered for watcher") from exc
        try:
            canonical_json_bytes(payload.config)
            validator(payload.config)
            return _snapshot_response(
                store.put_config(watcher_id, payload.config_version, payload.config, current.subject)
            )
        except (ContractError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    @app.put("/v1/jobs/{job_id}/schedule")
    def put_schedule(
        job_id: str,
        payload: ScheduleWrite,
        current: Principal = Depends(admin_only),
    ) -> dict[str, Any]:
        try:
            return _job_response(
                store.put_schedule(
                    job_id,
                    payload.enabled,
                    payload.interval_seconds,
                    payload.timezone,
                    current.subject,
                )
            )
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="scheduler job not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except (ContractError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    @app.post("/v1/runs", status_code=status.HTTP_201_CREATED)
    def start_run(payload: RunStart, _current: Principal = Depends(machine_or_admin)) -> dict[str, Any]:
        try:
            validate_watcher_id(payload.watcher_id)
            return _run_response(
                store.start_run(
                    payload.watcher_id,
                    payload.config_revision,
                    payload.scheduler_job_id,
                    payload.trigger,
                    payload.run_id,
                )
            )
        except (ContractError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    @app.post("/v1/runs/{run_id}/events", status_code=status.HTTP_201_CREATED)
    def append_event(
        run_id: str,
        payload: RunEvent,
        _current: Principal = Depends(machine_or_admin),
    ) -> dict[str, Any]:
        try:
            parsed = datetime.fromisoformat(payload.occurred_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="occurred_at must be ISO") from exc
        if parsed.tzinfo is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="occurred_at must include a timezone")
        try:
            attributes_bytes = json.dumps(
                payload.attributes,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="attributes must be finite JSON") from exc
        if len(attributes_bytes) > 64 * 1024:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="attributes are too large")
        try:
            event = store.append_event(
                EventRecord(
                    run_id=run_id,
                    event_id=payload.event_id,
                    occurred_at=payload.occurred_at,
                    level=payload.level,
                    phase=payload.phase,
                    event_type=payload.event_type,
                    message=payload.message,
                    attributes=payload.attributes,
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        return _event_response(event)

    @app.post("/v1/runs/{run_id}/finish")
    def finish_run(
        run_id: str,
        payload: RunFinish,
        _current: Principal = Depends(machine_or_admin),
    ) -> dict[str, Any]:
        try:
            return _run_response(store.finish_run(run_id, payload.status, payload.error))
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="run not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    return app


def create_app_from_environment() -> FastAPI:
    mode = os.environ.get("CONTROL_PLANE_STORE", "").strip().lower()
    if mode == "memory":
        store: Store = InMemoryStore()
    elif mode == "postgres":
        dsn = os.environ.get("DATABASE_URL", "").strip()
        if not dsn:
            raise RuntimeError("DATABASE_URL is required when CONTROL_PLANE_STORE=postgres")
        store = PostgresStore(dsn)
    else:
        raise RuntimeError("set CONTROL_PLANE_STORE=memory or CONTROL_PLANE_STORE=postgres")
    origins = [
        origin.strip()
        for origin in os.environ.get("CONTROL_PLANE_ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    ]
    if "*" in origins:
        raise RuntimeError("CONTROL_PLANE_ALLOWED_ORIGINS cannot contain * when credentials are enabled")
    return create_app(
        store=store,
        auth=auth_from_environment(),
        validators=validators_from_environment(),
        allowed_origins=origins,
    )


if os.environ.get("CONTROL_PLANE_STORE"):
    app = create_app_from_environment()
else:
    app = create_app(InMemoryStore())
