"""Scaffold for backend/app/api/v1/reconciliation; implementation pending."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.engines.reconciliation.matcher import ReconciliationMatch, ReconciliationStatus, compute_run_id
from app.engines.reconciliation.service import ReconciliationService
from app.schemas.common import ApiResponse, CursorPaginationMeta, PaginatedResponse
from app.schemas.reconciliation import (
    ReconciliationMatchStatus,
    ReconciliationResult,
    ReconciliationRun,
    ReconciliationRunCreate,
    ReconciliationRunState,
)

router = APIRouter(prefix="/reconciliation", tags=["Reconciliation"])


@router.post(
    "/runs",
    response_model=ApiResponse[ReconciliationRun],
    status_code=status.HTTP_201_CREATED,
    summary="Create or fetch an idempotent reconciliation run",
)
def create_reconciliation_run(
    payload: ReconciliationRunCreate,
    request: Request,
    db: Session = Depends(get_db),
) -> ApiResponse[ReconciliationRun]:
    req_id = getattr(request.state, "request_id", "unknown-request-id")
    run_id = compute_run_id(
        source_left_id=payload.source_left_id,
        source_right_id=payload.source_right_id,
        start_at=payload.start_at,
        cutoff_at=payload.cutoff_at,
        currency=payload.currency,
        policy_version=payload.policy_version_id,
        input_checkpoint=payload.input_checkpoint,
    )
    run = ReconciliationRun(
        id=run_id,
        source_left_id=payload.source_left_id,
        source_right_id=payload.source_right_id,
        start_at=payload.start_at,
        cutoff_at=payload.cutoff_at,
        policy_version_id=payload.policy_version_id,
        input_checkpoint=payload.input_checkpoint,
        state=ReconciliationRunState.COMPLETED,
        created_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
        total_count=0,
        matched_count=0,
        mismatch_count=0,
        missing_count=0,
    )
    return ApiResponse(data=run, meta={"run_id": run_id}, request_id=req_id)


@router.get(
    "/runs/{run_id}/results",
    response_model=PaginatedResponse[ReconciliationResult],
    status_code=status.HTTP_200_OK,
    summary="Return paginated reconciliation results for a run",
)
def get_reconciliation_results(
    request: Request,
    run_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> PaginatedResponse[ReconciliationResult]:
    req_id = getattr(request.state, "request_id", "unknown-request-id")
    _ = run_id
    items: list[ReconciliationResult] = []
    meta = CursorPaginationMeta(next_cursor=None, has_more=False, total_count=len(items), limit=limit)
    return PaginatedResponse(data=tuple(items[offset : offset + limit]), meta=meta, request_id=req_id)
