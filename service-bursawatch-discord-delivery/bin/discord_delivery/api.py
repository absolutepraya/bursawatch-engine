"""Authenticated submission and status API. Query execution is injected by the gateway."""

from __future__ import annotations

import hmac
import json
from email.parser import BytesParser
from email.policy import default
from typing import Any, Callable

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .config import Config
from .discord_gateway import GatewayError
from .models import Attachment, OperationIntent, ValidationError, validate_preflight, validate_query
from .store import DeliveryStore, OperationKeyConflict, OperationStateConflict

QueryExecutor = Callable[[dict[str, Any]], Any]
MAX_REQUEST_BYTES = 26 * 1024 * 1024


def _authorized(header: str | None, token: str) -> None:
    if not header or not header.startswith("Bearer ") or not hmac.compare_digest(header[7:], token):
        raise HTTPException(401, "unauthorized")


def _submit_scope(header: str | None, config: Config) -> str:
    if not header or not header.startswith("Bearer "):
        raise HTTPException(401, "unauthorized")
    presented = header[7:]
    client = hmac.compare_digest(presented, config.api_token)
    emoji = config.emoji_token is not None and hmac.compare_digest(presented, config.emoji_token)
    if not client and not emoji:
        raise HTTPException(401, "unauthorized")
    return "emoji" if emoji else "client"


def _parse_intent(data: dict[str, Any], attachments: tuple[Attachment, ...] = (),
                  *, allow_legacy_nonce: bool = False) -> OperationIntent:
    if not isinstance(data, dict) or not {"key", "kind", "ordering_key", "target", "payload"} <= set(data):
        raise ValidationError("missing operation fields")
    allowed = {"key", "kind", "ordering_key", "target", "payload", "reconcile_before_first_create"}
    if allow_legacy_nonce:
        allowed.add("legacy_nonce")
    if set(data) - allowed:
        raise ValidationError("invalid operation fields")
    return OperationIntent(
        key=data["key"], kind=data["kind"], ordering_key=data["ordering_key"],
        target=data["target"], payload=data["payload"], attachments=attachments,
        reconcile_before_first_create=data.get("reconcile_before_first_create", False),
        legacy_nonce=data.get("legacy_nonce"),
    )


async def _multipart_operation(request: Request) -> OperationIntent:
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data;") or "boundary=" not in content_type:
        raise ValidationError("multipart form required")
    try:
        if int(request.headers.get("content-length", "0")) > MAX_REQUEST_BYTES:
            raise ValidationError("request too large")
    except ValueError as exc:
        raise ValidationError("invalid request length") from exc
    body = await request.body()
    if len(body) > MAX_REQUEST_BYTES:
        raise ValidationError("request too large")
    message = BytesParser(policy=default).parsebytes(
        b"MIME-Version: 1.0\r\nContent-Type: " + content_type.encode("ascii", errors="ignore") + b"\r\n\r\n" + body)
    if not message.is_multipart():
        raise ValidationError("invalid multipart body")
    operation = None
    attachments = []
    for part in message.iter_parts():
        disposition = part.get_content_disposition()
        name = part.get_param("name", header="content-disposition")
        if disposition != "form-data" or name not in {"operation", "attachments"}:
            raise ValidationError("invalid multipart field")
        content = part.get_payload(decode=True)
        if name == "operation":
            if operation is not None or len(content) > 65536:
                raise ValidationError("invalid operation part")
            try:
                operation = json.loads(content)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValidationError("invalid operation JSON") from exc
        else:
            attachments.append(Attachment(part.get_filename(), part.get_content_type(), content))
    if not isinstance(operation, dict):
        raise ValidationError("missing operation")
    return _parse_intent(operation, tuple(attachments))


async def _multipart_adoption(request: Request) -> tuple[dict[str, Any], tuple[Attachment, ...]]:
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data;") or "boundary=" not in content_type:
        raise ValidationError("multipart form required")
    try:
        if int(request.headers.get("content-length", "0")) > MAX_REQUEST_BYTES:
            raise ValidationError("request too large")
    except ValueError as exc:
        raise ValidationError("invalid request length") from exc
    body = await request.body()
    if len(body) > MAX_REQUEST_BYTES:
        raise ValidationError("request too large")
    message = BytesParser(policy=default).parsebytes(
        b"MIME-Version: 1.0\r\nContent-Type: "
        + content_type.encode("ascii", errors="ignore")
        + b"\r\n\r\n"
        + body
    )
    if not message.is_multipart():
        raise ValidationError("invalid multipart body")
    adoption = None
    attachments = []
    for part in message.iter_parts():
        disposition = part.get_content_disposition()
        name = part.get_param("name", header="content-disposition")
        if disposition != "form-data" or name not in {"adoption", "attachments"}:
            raise ValidationError("invalid multipart field")
        content = part.get_payload(decode=True)
        if name == "adoption":
            if adoption is not None or content is None or len(content) > 65536:
                raise ValidationError("invalid adoption part")
            try:
                adoption = json.loads(content)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValidationError("invalid adoption JSON") from exc
        else:
            attachments.append(Attachment(part.get_filename(), part.get_content_type(), content))
    if not isinstance(adoption, dict):
        raise ValidationError("missing adoption envelope")
    return adoption, tuple(attachments)


def _public(record: Any) -> dict[str, Any]:
    return {"id": record.id, "key": record.key, "digest": record.digest,
            "status": record.status, "receipt": record.receipt}


def _summary(record: Any) -> dict[str, Any]:
    return {"id": record.id, "key": record.key, "digest": record.digest,
            "kind": record.kind, "ordering_key": record.ordering_key,
            "target": record.target, "status": record.status,
            "created_at": record.created_at, "updated_at": record.updated_at,
            "attempt_count": record.attempt_count, "error_category": record.error_category}


def create_app(config: Config, store: DeliveryStore | None = None,
               query_executor: QueryExecutor | None = None) -> FastAPI:
    store = store or DeliveryStore(config.state_path, config.media_path)
    app = FastAPI(title="Bursawatch Discord Delivery", version="1.0.0")

    @app.exception_handler(ValidationError)
    async def validation_error(_request: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(OperationKeyConflict)
    async def key_conflict(_request: Request, _exc: OperationKeyConflict) -> JSONResponse:
        return JSONResponse({"detail": "operation key conflicts with an existing payload"}, status_code=409)

    @app.exception_handler(OperationStateConflict)
    async def state_conflict(_request: Request, _exc: OperationStateConflict) -> JSONResponse:
        return JSONResponse({"detail": "operation state or digest mismatch"}, status_code=409)

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {"status": "ok", "operations": store.counts()}

    @app.post("/v1/operations", status_code=202)
    async def submit(request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
        scope = _submit_scope(authorization, config)
        intent = await _multipart_operation(request)
        if (intent.kind == "guild_emoji_create") != (scope == "emoji"):
            raise HTTPException(403, "operation not authorized for token")
        return _public(store.accept(intent))

    @app.post("/v1/operations/adopt", status_code=202)
    async def adopt(request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
        _authorized(authorization, config.admin_token)
        content_type = request.headers.get("content-type", "")
        if content_type.lower().startswith("multipart/form-data;"):
            data, attachments = await _multipart_adoption(request)
        else:
            try:
                data = await request.json()
            except (ValueError, UnicodeDecodeError) as exc:
                raise ValidationError("invalid JSON") from exc
            attachments = ()
        if not isinstance(data, dict) or not {"action", "operation"} <= set(data):
            raise ValidationError("invalid import fields")
        fields = set(data)
        if data["action"] == "completed":
            if fields not in (
                {"action", "operation", "receipt"},
                {"action", "operation", "receipt", "payload_digest"},
            ):
                raise ValidationError("invalid import fields")
        elif data["action"] == "pending":
            if fields not in (
                {"action", "operation"},
                {"action", "operation", "payload_digest"},
                {"action", "operation", "preflight"},
                {"action", "operation", "payload_digest", "preflight"},
            ):
                raise ValidationError("invalid import fields")
        else:
            raise ValidationError("invalid import action")
        intent = _parse_intent(data["operation"], attachments,
                               allow_legacy_nonce=data["action"] == "pending")
        if "payload_digest" in data and data["payload_digest"] != intent.digest:
            raise ValidationError("import payload digest mismatch")
        if data["action"] == "completed" and "receipt" in data:
            return _public(store.adopt_completed(intent, data["receipt"]))
        if data["action"] == "pending" and "receipt" not in data:
            preflight = None
            if "preflight" in data:
                preflight = validate_preflight(data["preflight"], str(intent.kind))
                if preflight is None:
                    raise ValidationError("invalid preflight boundary")
            return _public(store.adopt_pending(intent, preflight=preflight))
        raise ValidationError("invalid import action")

    @app.get("/v1/operations/by-key/{operation_key:path}")
    def by_key(operation_key: str, authorization: str | None = Header(default=None)) -> dict[str, Any]:
        _authorized(authorization, config.api_token)
        record = store.get_by_key(operation_key)
        if record is None:
            raise HTTPException(404, "operation not found")
        return _public(record)

    @app.post("/v1/queries")
    async def query(request: Request, authorization: str | None = Header(default=None)) -> Any:
        _authorized(authorization, config.api_token)
        try:
            data = await request.json()
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValidationError("invalid JSON") from exc
        validated = validate_query(data)
        if query_executor is None:
            raise HTTPException(503, "query gateway unavailable")
        try:
            return await run_in_threadpool(query_executor, validated)
        except GatewayError as exc:
            headers = {}
            if exc.category == "rate_limited" and exc.retry_after is not None:
                delay = float(exc.retry_after)
                headers["Retry-After"] = str(int(delay) if delay.is_integer() else delay)
            raise HTTPException(503, "Discord query unavailable", headers=headers) from None

    @app.get("/v1/admin/operations")
    def admin_list(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=100000),
                   authorization: str | None = Header(default=None)) -> dict[str, Any]:
        _authorized(authorization, config.admin_token)
        return {"operations": [_summary(record) for record in store.list_summaries(limit, offset)],
                "limit": limit, "offset": offset}

    @app.post("/v1/admin/operations/{operation_key:path}/retry")
    async def retry(operation_key: str, request: Request,
                    authorization: str | None = Header(default=None)) -> dict[str, Any]:
        _authorized(authorization, config.admin_token)
        try:
            data = await request.json()
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValidationError("invalid JSON") from exc
        if not isinstance(data, dict) or set(data) != {"expected_digest"}:
            raise ValidationError("expected digest required")
        return _summary(store.retry_blocked(operation_key, data["expected_digest"]))

    return app
