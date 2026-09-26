from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
import json
import os
from typing import Any, Callable, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from .auth import Authenticator, AuthenticationError, Principal, StaticTokenAuth, auth_from_environment
from .contract import ConfigSnapshot, ContractError, canonical_json_bytes, validate_watcher_id
from .profile_metadata import (
    AvatarResolutionError,
    AvatarResolver,
    ProfileMetadataInput,
    RssHubAvatarResolver,
    normalize_manual_avatar_url,
    profile_inputs_from_config,
    validate_profile_id,
)
from .postgres_pool import create_postgres_pool
from .store import (
    EventRecord,
    InMemoryStore,
    PostgresStore,
    ProfileAvatarRecord,
    RunRecord,
    ScheduleRevisionConflictError,
    SchedulerJobRecord,
    Store,
)
from .source_catalog import (
    CatalogConflict,
    MemoryCatalogStore,
    PostgresCatalogStore,
    catalog_view,
    effective_snapshot,
)
from .source_inbox import InboxConflict, MemoryInboxStore, PostgresInboxStore
from .validators import validators_from_environment


class ConfigWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config_version: int = Field(ge=1)
    config: dict[str, Any]


class CatalogWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=1)
    config: dict[str, Any]


class SourceEventWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    envelope: dict[str, Any]


class WorkSettle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lease_token: str = Field(min_length=1, max_length=64)
    success: bool
    error_code: str | None = None


class WorkFence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lease_token: str = Field(min_length=1, max_length=64)


class WorkClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pipeline_ids: list[str] = Field(min_length=1, max_length=32)


class WorkAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=1, max_length=500)


class WorkRecover(WorkAction):
    worker_stopped: StrictBool


class SourceRevisionWrite(WorkAction):
    envelope: dict[str, Any]
    kind: Literal["correction", "tombstone"]
    revision_id: str = Field(min_length=1, max_length=128)


class AvatarWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["auto", "manual"]
    url: str | None = Field(default=None, max_length=2_048)

    @model_validator(mode="after")
    def validate_url_for_mode(self) -> "AvatarWrite":
        if self.mode == "manual":
            normalize_manual_avatar_url(self.url)
        elif self.url is not None:
            raise ValueError("auto avatar mode must not include a URL")
        return self


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


class ScheduleReconciliationWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=1)
    status: Literal["applied", "error"]
    error: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_status_error(self) -> "ScheduleReconciliationWrite":
        if self.status == "applied" and self.error is not None:
            raise ValueError("applied reconciliation cannot include an error")
        if self.status == "error" and (self.error is None or not self.error.strip()):
            raise ValueError("failed reconciliation requires a non-empty error")
        return self


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


def _profile_avatar_response(record: ProfileAvatarRecord) -> dict[str, Any]:
    return {
        "watcher_id": record.watcher_id,
        "profile_id": record.profile_id,
        "handle": record.handle,
        "display_name": record.display_name,
        "profile_url": record.profile_url,
        "enabled": record.enabled,
        "avatar": {
            "mode": record.avatar_mode,
            "url": record.avatar_url,
            "source": record.avatar_source,
            "fetched_at": record.fetched_at,
            "last_success_at": record.last_success_at,
            "last_error": record.last_error,
            "updated_at": record.updated_at,
        },
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
            "last_error": job.reconciliation_error,
            "effective": effective,
        },
    }


def create_app(
    store: Store | None = None,
    auth: Authenticator | None = None,
    validators: dict[str, Callable[[dict[str, Any]], None]] | None = None,
    allowed_origins: list[str] | None = None,
    avatar_resolver: AvatarResolver | None = None,
    catalog_store: MemoryCatalogStore | PostgresCatalogStore | None = None,
    inbox_store: MemoryInboxStore | PostgresInboxStore | None = None,
) -> FastAPI:
    store = store or InMemoryStore()
    auth = auth or StaticTokenAuth.from_environment()
    validators = validators or {}
    pool = store.pool if isinstance(store, PostgresStore) else None
    catalog_store = catalog_store or (PostgresCatalogStore(store.dsn, pool=pool) if isinstance(store, PostgresStore) else MemoryCatalogStore())
    inbox_store = inbox_store or (PostgresInboxStore(store.dsn, catalog_store, pool=pool) if isinstance(store, PostgresStore) else MemoryInboxStore(catalog_store))

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            if pool is not None:
                pool.open(wait=True, timeout=10.0)
            yield
        finally:
            if pool is not None:
                pool.close()

    app = FastAPI(title="Bursawatch Control Plane", version="1.0.0", lifespan=lifespan)
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

    def source_event_principal(current: Principal = Depends(principal)) -> Principal:
        if current.kind not in {"machine", "source_machine", "admin"}:
            raise HTTPException(status_code=403, detail="source event role required")
        return current

    def worker_or_admin(current: Principal = Depends(principal)) -> Principal:
        if current.kind not in {"machine", "admin"}:
            raise HTTPException(status_code=403, detail="worker role required")
        return current

    def admin_only(current: Principal = Depends(principal)) -> Principal:
        if current.kind != "admin":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin role required")
        return current

    def human_reader(current: Principal = Depends(principal)) -> Principal:
        if current.kind not in {"admin", "viewer"}:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="signed-in user required")
        return current

    def reconciler_only(current: Principal = Depends(principal)) -> Principal:
        if current.kind != "reconciler":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="schedule reconciler role required")
        return current

    def current_profile_metadata(watcher_id: str) -> list[ProfileAvatarRecord]:
        snapshot = store.get_config(watcher_id)
        profiles = profile_inputs_from_config(snapshot.config)
        return store.sync_profile_metadata(watcher_id, profiles)

    def refresh_avatar(record: ProfileAvatarRecord) -> None:
        if avatar_resolver is None or record.avatar_mode != "auto":
            return
        profile = ProfileMetadataInput(
            profile_id=record.profile_id,
            handle=record.handle,
            display_name=record.display_name,
            profile_url=record.profile_url,
            enabled=record.enabled,
        )
        try:
            resolution = avatar_resolver.resolve(profile)
            store.record_profile_avatar_success(
                record.watcher_id,
                record.profile_id,
                resolution.url,
                resolution.source,
                record.handle,
                record.profile_url,
            )
        except (AvatarResolutionError, KeyError, ValueError) as exc:
            store.record_profile_avatar_failure(
                record.watcher_id,
                record.profile_id,
                str(exc),
                record.handle,
                record.profile_url,
            )

    def queue_initial_avatar_refresh(
        records: list[ProfileAvatarRecord],
        background_tasks: BackgroundTasks,
    ) -> None:
        if avatar_resolver is None:
            return
        for record in records:
            if record.avatar_mode == "auto" and record.last_success_at is None:
                background_tasks.add_task(refresh_avatar, record)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/source-catalog")
    def get_source_catalog(current_user: Principal = Depends(human_reader)) -> dict[str, Any]:
        current = catalog_store.get()
        return {**catalog_view(current["config"], catalog_store.registry()), "config": current, "can_edit": current_user.kind == "admin"}

    @app.get("/v1/source-catalog/effective")
    def get_effective_catalog(_current: Principal = Depends(principal)) -> dict[str, Any]:
        if _current.kind not in {"admin", "viewer", "machine"}:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient role")
        current = catalog_store.get()
        return effective_snapshot(current["config"], catalog_view(current["config"], catalog_store.registry()), current["revision"], current["updated_at"])

    @app.put("/v1/source-catalog/config")
    def put_source_catalog(payload: CatalogWrite, current: Principal = Depends(admin_only)) -> dict[str, Any]:
        try:
            return catalog_store.put(payload.expected_revision, payload.config, current.subject)
        except CatalogConflict as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    @app.post("/v1/source-events")
    def accept_source_event(payload: SourceEventWrite, current: Principal = Depends(source_event_principal)) -> dict[str, Any]:
        if current.kind == "source_machine" and payload.envelope.get("endpoint_id") != current.subject:
            raise HTTPException(status_code=403, detail="source endpoint credential mismatch")
        try:
            return inbox_store.accept(payload.envelope)
        except InboxConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, TypeError, KeyError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/source-work/claim")
    def claim_source_work(payload: WorkClaim, limit: int = Query(default=10, ge=1, le=100), _current: Principal = Depends(worker_or_admin)) -> list[dict[str, Any]]:
        try:
            return inbox_store.claim(payload.pipeline_ids, limit)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/source-work/{work_key}/begin")
    def begin_source_work(work_key: str, payload: WorkFence, _current: Principal = Depends(worker_or_admin)) -> dict[str, bool]:
        return {"begun": inbox_store.begin(work_key, payload.lease_token)}

    @app.get("/v1/source-work")
    def list_source_work(status: Literal["pending", "leased", "executing", "done", "dead_letter", "suppressed", "superseded"], limit: int = Query(default=100, ge=1, le=100), _current: Principal = Depends(worker_or_admin)) -> list[dict[str, Any]]:
        return inbox_store.list_work(status, limit)

    @app.post("/v1/source-work/{work_key}/settle")
    def settle_source_work(work_key: str, payload: WorkSettle, _current: Principal = Depends(worker_or_admin)) -> dict[str, Any]:
        try:
            return inbox_store.settle(work_key, payload.lease_token, success=payload.success, error_code=payload.error_code)
        except InboxConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/source-work/{work_key}/fence")
    def fence_source_work(work_key: str, payload: WorkFence, _current: Principal = Depends(worker_or_admin)) -> dict[str, bool]:
        return {"current": inbox_store.fence(work_key, payload.lease_token)}

    @app.get("/v1/source-events/{event_key}")
    def inspect_source_event(event_key: str, _current: Principal = Depends(worker_or_admin)) -> dict[str, Any]:
        try:
            return inbox_store.inspect(event_key)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="source event not found") from exc

    @app.post("/v1/source-work/{work_key}/suppress")
    def suppress_source_work(work_key: str, payload: WorkAction, current: Principal = Depends(admin_only)) -> dict[str, Any]:
        try:
            return inbox_store.suppress(work_key, current.subject, payload.reason)
        except InboxConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v1/source-work/{work_key}/replay")
    def replay_source_work(work_key: str, payload: WorkAction, current: Principal = Depends(admin_only)) -> dict[str, Any]:
        try:
            return inbox_store.replay(work_key, current.subject, payload.reason)
        except InboxConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/v1/source-work/{work_key}/recover")
    def recover_source_work(work_key: str, payload: WorkRecover, current: Principal = Depends(admin_only)) -> dict[str, Any]:
        try:
            return inbox_store.recover(work_key, current.subject, payload.reason, payload.worker_stopped)
        except InboxConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/source-events/{event_key}/versions")
    def revise_source_event(event_key: str, payload: SourceRevisionWrite, current: Principal = Depends(source_event_principal)) -> dict[str, Any]:
        if current.kind not in {"admin", "source_machine"}:
            raise HTTPException(status_code=403, detail="source revision role required")
        if current.kind == "source_machine" and payload.envelope.get("endpoint_id") != current.subject:
            raise HTTPException(status_code=403, detail="source endpoint credential mismatch")
        try:
            return inbox_store.revise(event_key, payload.envelope, payload.kind, payload.revision_id, current.subject, payload.reason)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="source event not found") from exc
        except InboxConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/watchers")
    def list_watchers(_current: Principal = Depends(human_reader)) -> list[dict[str, Any]]:
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

    @app.get("/v1/watchers/{watcher_id}/profiles")
    def list_profiles(watcher_id: str, _current: Principal = Depends(human_reader)) -> list[dict[str, Any]]:
        try:
            validate_watcher_id(watcher_id)
            return [_profile_avatar_response(record) for record in current_profile_metadata(watcher_id)]
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="watcher profiles not found") from exc
        except (ContractError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    @app.get("/v1/watchers/{watcher_id}/runs")
    def list_runs(
        watcher_id: str,
        limit: int = Query(default=50, ge=1, le=200),
        _current: Principal = Depends(human_reader),
    ) -> list[dict[str, Any]]:
        try:
            validate_watcher_id(watcher_id)
            return [_run_response(run) for run in store.list_runs(watcher_id, limit)]
        except ContractError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    @app.get("/v1/watchers/{watcher_id}/jobs")
    def list_jobs(
        watcher_id: str,
        _current: Principal = Depends(human_reader),
    ) -> list[dict[str, Any]]:
        try:
            validate_watcher_id(watcher_id)
            return [_job_response(job) for job in store.list_jobs(watcher_id)]
        except ContractError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    @app.get("/v1/jobs/{job_id}/schedule")
    def get_schedule(job_id: str, _current: Principal = Depends(human_reader)) -> dict[str, Any]:
        try:
            return _job_response(store.get_job(job_id))
        except (ContractError, KeyError) as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="scheduler job not found") from exc

    @app.get("/v1/internal/schedules")
    def list_reconcilable_schedules(_current: Principal = Depends(reconciler_only)) -> list[dict[str, Any]]:
        return [_job_response(job) for job in store.list_reconcilable_jobs()]

    @app.get("/v1/watchers/{watcher_id}/events")
    def list_watcher_events(
        watcher_id: str,
        limit: int = Query(default=500, ge=1, le=1000),
        _current: Principal = Depends(human_reader),
    ) -> list[dict[str, Any]]:
        try:
            validate_watcher_id(watcher_id)
            return [_event_response(event) for event in store.list_watcher_events(watcher_id, limit)]
        except ContractError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    @app.get("/v1/runs/{run_id}/events")
    def list_events(
        run_id: str,
        limit: int = Query(default=500, ge=1, le=1000),
        _current: Principal = Depends(human_reader),
    ) -> list[dict[str, Any]]:
        return [_event_response(event) for event in store.list_events(run_id, limit)]

    @app.put("/v1/watchers/{watcher_id}/config")
    def put_config(
        watcher_id: str,
        payload: ConfigWrite,
        background_tasks: BackgroundTasks,
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
            profiles = profile_inputs_from_config(payload.config)
            snapshot = store.put_config(watcher_id, payload.config_version, payload.config, current.subject)
            records = store.sync_profile_metadata(watcher_id, profiles)
            queue_initial_avatar_refresh(records, background_tasks)
            return _snapshot_response(snapshot)
        except (ContractError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    @app.put("/v1/watchers/{watcher_id}/profiles/{profile_id}/avatar")
    def put_profile_avatar(
        watcher_id: str,
        profile_id: str,
        payload: AvatarWrite,
        background_tasks: BackgroundTasks,
        _current: Principal = Depends(admin_only),
    ) -> dict[str, Any]:
        try:
            validate_watcher_id(watcher_id)
            validate_profile_id(profile_id)
            records = current_profile_metadata(watcher_id)
            if not any(record.profile_id == profile_id for record in records):
                raise KeyError((watcher_id, profile_id))
            record = store.set_profile_avatar(watcher_id, profile_id, payload.mode, payload.url)
            queue_initial_avatar_refresh([record], background_tasks)
            return _profile_avatar_response(record)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="profile not found") from exc
        except (ContractError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    @app.post("/v1/watchers/{watcher_id}/profiles/{profile_id}/avatar/refresh")
    def refresh_profile_avatar(
        watcher_id: str,
        profile_id: str,
        background_tasks: BackgroundTasks,
        _current: Principal = Depends(admin_only),
    ) -> dict[str, Any]:
        try:
            validate_watcher_id(watcher_id)
            validate_profile_id(profile_id)
            records = current_profile_metadata(watcher_id)
            try:
                record = next(record for record in records if record.profile_id == profile_id)
            except StopIteration as exc:
                raise KeyError((watcher_id, profile_id)) from exc
            if record.avatar_mode == "auto":
                background_tasks.add_task(refresh_avatar, record)
            return _profile_avatar_response(record)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="profile not found") from exc
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

    @app.post("/v1/internal/jobs/{job_id}/reconciliation")
    def record_schedule_reconciliation(
        job_id: str,
        payload: ScheduleReconciliationWrite,
        _current: Principal = Depends(reconciler_only),
    ) -> dict[str, Any]:
        try:
            return _job_response(
                store.record_schedule_reconciliation(
                    job_id,
                    payload.revision,
                    payload.status,
                    payload.error,
                )
            )
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="scheduler job not found") from exc
        except (PermissionError, ScheduleRevisionConflictError) as exc:
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
        store = PostgresStore(dsn, pool=create_postgres_pool(dsn))
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
        avatar_resolver=RssHubAvatarResolver.from_environment(),
    )


if os.environ.get("CONTROL_PLANE_STORE"):
    app = create_app_from_environment()
else:
    app = create_app(InMemoryStore())
