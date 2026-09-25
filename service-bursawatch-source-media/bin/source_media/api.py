"""Authenticated loopback source-media API."""

from __future__ import annotations

import hmac
from urllib.parse import quote_from_bytes, unquote_to_bytes

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from .config import Config
from .models import (
    IdempotencyConflict,
    MAX_OBJECT_BYTES,
    ObjectNotFound,
    StorageError,
    ValidationError,
    validate_upload,
)
from .store import MediaStore


async def _read_bounded_body(request: Request) -> bytes:
    declared_size = request.headers.get("content-length")
    if declared_size is not None:
        try:
            if int(declared_size) > MAX_OBJECT_BYTES:
                raise ValidationError("media object exceeds 8 MiB")
        except ValueError as exc:
            raise ValidationError("invalid content length") from exc
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_OBJECT_BYTES:
            raise ValidationError("media object exceeds 8 MiB")
    return bytes(data)


def _decode_filename(value: str | None) -> str:
    if not value:
        raise ValidationError("missing media filename")
    try:
        return unquote_to_bytes(value).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationError("invalid media filename") from exc


def _authorized(header: str | None, expected: str) -> None:
    if not header or not header.startswith("Bearer ") or not hmac.compare_digest(header[7:], expected):
        raise HTTPException(401, "unauthorized")


def create_app(config: Config, store: MediaStore) -> FastAPI:
    app = FastAPI(title="Bursawatch Source Media Owner", version="1.0.0")

    @app.exception_handler(ValidationError)
    async def validation_error(_request: Request, exc: ValidationError) -> Response:
        return Response(content=str(exc), status_code=422, media_type="text/plain")

    @app.exception_handler(IdempotencyConflict)
    async def conflict(_request: Request, _exc: IdempotencyConflict) -> Response:
        return Response(content="upload key conflicts with an existing payload", status_code=409)

    @app.exception_handler(ObjectNotFound)
    async def not_found(_request: Request, _exc: ObjectNotFound) -> Response:
        return Response(content="media reference not found", status_code=404)

    @app.exception_handler(StorageError)
    async def storage_error(_request: Request, _exc: StorageError) -> Response:
        return Response(content="private media storage is unavailable", status_code=502)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/objects", status_code=201)
    async def upload(
        request: Request,
        authorization: str | None = Header(default=None),
        idempotency_key: str | None = Header(default=None, alias="X-Idempotency-Key"),
        kind: str | None = Header(default=None, alias="X-Media-Kind"),
        content_type: str | None = Header(default=None, alias="X-Media-Content-Type"),
        filename: str | None = Header(default=None, alias="X-Media-Filename"),
    ) -> dict[str, object]:
        _authorized(authorization, config.upload_token)
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/octet-stream":
            raise ValidationError("application/octet-stream request body required")
        if not idempotency_key or not kind or not content_type:
            raise ValidationError("missing upload metadata")
        data = await _read_bounded_body(request)
        filename_value = _decode_filename(filename)
        # Validate before entering the blocking provider/SQLite call. MediaStore
        # repeats this validation as the durable boundary.
        validate_upload(
            idempotency_key=idempotency_key,
            data=data,
            kind=kind,
            content_type=content_type,
            filename=filename_value,
        )
        metadata = await run_in_threadpool(
            store.upload,
            idempotency_key,
            data,
            kind=kind,
            content_type=content_type,
            filename=filename_value,
        )
        return metadata.as_dict()

    @app.get("/v1/objects/{ref}")
    def download(ref: str, authorization: str | None = Header(default=None)) -> Response:
        _authorized(authorization, config.read_token)
        stored = store.download(ref)
        metadata = stored.metadata
        return Response(
            content=stored.data,
            media_type=metadata.content_type,
            headers={
                "X-Media-Sha256": metadata.sha256,
                "X-Media-Kind": metadata.kind,
                "X-Media-Filename": quote_from_bytes(metadata.filename.encode("utf-8"), safe=""),
                "X-Media-Size-Bytes": str(metadata.size_bytes),
                "Cache-Control": "private, no-store",
                "Content-Disposition": "attachment",
            },
        )

    return app
