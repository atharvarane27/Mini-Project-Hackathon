"""Streaming CSV ingestion job endpoints."""

from __future__ import annotations

import hashlib
from io import TextIOWrapper
from collections.abc import Callable
from uuid import uuid4

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile, status

from app.ingestion.service import (
    IngestionIdempotencyConflict,
    IngestionJob,
    IngestionService,
)


IngestFunction = Callable[..., IngestionJob]


def create_ingestion_router(
    service: IngestionService,
    *,
    ingest: IngestFunction | None = None,
) -> APIRouter:
    router = APIRouter()
    ingest_file = ingest or service.ingest

    @router.post("/ingestion/jobs", status_code=status.HTTP_202_ACCEPTED)
    def create_job(
        file: UploadFile = File(...),
        source_system: str = Form(...),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        request_id_header: str | None = Header(default=None, alias="X-Request-ID"),
    ) -> dict[str, object]:
        if idempotency_key is None:
            raise HTTPException(400, detail={"code": "IDEMPOTENCY_KEY_REQUIRED"})
        digest = hashlib.sha256()
        while chunk := file.file.read(1024 * 1024):
            digest.update(chunk)
        file.file.seek(0)
        text = TextIOWrapper(file.file, encoding="utf-8-sig", newline="")
        try:
            job = ingest_file(
                text,
                source_system=source_system,
                source_file=file.filename or "upload.csv",
                file_hash=digest.hexdigest(),
                idempotency_key=idempotency_key,
            )
        except IngestionIdempotencyConflict as error:
            raise HTTPException(
                409, detail={"code": "IDEMPOTENCY_CONFLICT", "message": str(error)}
            ) from error
        finally:
            text.detach()
        return {
            "data": job.as_dict(), "meta": {},
            "request_id": request_id_header or str(uuid4()),
        }

    @router.get("/ingestion/jobs/{job_id}")
    def get_job(
        job_id: str,
        request_id_header: str | None = Header(default=None, alias="X-Request-ID"),
    ) -> dict[str, object]:
        try:
            job = service.repository.get(job_id)
        except KeyError as error:
            raise HTTPException(404, detail={"code": "INGESTION_JOB_NOT_FOUND"}) from error
        return {
            "data": job.as_dict(), "meta": {},
            "request_id": request_id_header or str(uuid4()),
        }

    return router
