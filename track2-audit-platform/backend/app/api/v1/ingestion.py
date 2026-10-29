from __future__ import annotations

from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    Request,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, get_request_id
from app.db.session import get_db
from app.ingestion.service import IngestionService
from app.schemas.common import ApiResponse
from app.schemas.ingestion import IngestionJob

router = APIRouter(prefix="/ingestion", tags=["Ingestion"])


@router.post(
    "/jobs",
    response_model=ApiResponse[IngestionJob],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit CSV file for bounded streaming ingestion",
)
async def submit_ingestion_job(
    request: Request,
    file: Annotated[UploadFile, File(description="CSV transaction feed file")],
    source_system_id: Annotated[str, Form(description="Registered source system identifier")],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    db: Session = Depends(get_db),
) -> ApiResponse[IngestionJob]:
    """Stream and ingest a CSV file with bounded memory usage."""
    req_id = get_request_id(request)
    service = IngestionService()

    # Pass the underlying file-like object directly into the bounded batch streamer
    job = service.process_file_or_stream(
        stream_or_file=file.file,
        source_system_id=source_system_id,
        idempotency_key=idempotency_key,
        db_session=db,
    )

    return ApiResponse(
        data=job,
        meta={
            "filename": file.filename,
            "content_type": file.content_type,
        },
        request_id=req_id,
    )


@router.get(
    "/jobs/{job_id}",
    response_model=ApiResponse[IngestionJob],
    status_code=status.HTTP_200_OK,
    summary="Retrieve ingestion job status and counts",
)
async def get_ingestion_job(
    request: Request,
    job_id: str,
    db: Session = Depends(get_db),
) -> ApiResponse[IngestionJob]:
    """Retrieve the real-time execution status and error diagnostics of an ingestion job."""
    req_id = get_request_id(request)
    service = IngestionService()
    job = service.get_job(job_id=job_id, db_session=db)

    if not job:
        raise NotFoundError(message=f"Ingestion job '{job_id}' not found.")

    return ApiResponse(
        data=job,
        meta={},
        request_id=req_id,
    )
