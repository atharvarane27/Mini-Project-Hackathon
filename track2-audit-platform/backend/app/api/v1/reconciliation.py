"""Reconciliation API endpoints for run creation and result retrieval."""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ReconciliationResult as ReconciliationResultModel
from app.db.models import ReconciliationRun as ReconciliationRunModel
from app.db.models import SourceRecord, SourceSystem
from app.db.session import get_db
from app.engines.reconciliation.service import ReconciliationService
from app.schemas.common import ApiResponse, CursorPaginationMeta, PaginatedResponse
from app.schemas.reconciliation import ReconciliationResult, ReconciliationRun, ReconciliationRunCreate, ReconciliationRunState

router = APIRouter(prefix="/reconciliation", tags=["Reconciliation"])


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _encode_cursor(run_id: str, result_id: str) -> str:
    raw = f"{run_id}|{result_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("utf-8")).decode("utf-8")
        run_id, result_id = raw.split("|", 1)
        return run_id, result_id
    except Exception as exc:  # pragma: no cover - defensive API guard
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid reconciliation cursor: {exc}",
        ) from exc


def _read_ledger_records(db: Session, source_system_id: str, *, start_at: datetime, cutoff_at: datetime) -> list[dict[str, Any]]:
    records = (
        db.query(SourceRecord)
        .filter(
            SourceRecord.source_system_id == source_system_id,
            SourceRecord.received_at >= start_at,
            SourceRecord.received_at <= cutoff_at,
        )
        .order_by(SourceRecord.received_at.asc(), SourceRecord.id.asc())
        .all()
    )

    items: list[dict[str, Any]] = []
    for record in records:
        payload = record.payload_json or {}
        items.append(
            {
                "id": record.id,
                "external_ref": record.external_ref,
                "reference": payload.get("external_reference") or record.external_ref,
                "amount_minor": payload.get("amount_minor") or payload.get("transaction_amount") or 0,
                "currency": payload.get("currency") or "INR",
                "source": source_system_id,
                "occurred_at": payload.get("occurred_at") or record.received_at,
                "posted_at": payload.get("posted_at") or record.received_at,
            }
        )
    return items


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
    start_dt = payload.start_at.astimezone(UTC)
    cutoff_dt = payload.cutoff_at.astimezone(UTC)
    run_id = payload.idempotency_key or ReconciliationService().build_run_id(
        source_left_id=payload.source_left_id,
        source_right_id=payload.source_right_id,
        start_at=start_dt,
        cutoff_at=cutoff_dt,
        currency=payload.currency,
        policy_version=payload.policy_version_id,
        input_checkpoint=payload.input_checkpoint,
    )

    existing = db.query(ReconciliationRunModel).filter_by(id=run_id).first()
    if existing is not None:
        return ApiResponse(data=ReconciliationRun.model_validate(existing), meta={"run_id": run_id}, request_id=req_id)

    left_source = db.query(SourceSystem).filter_by(id=payload.source_left_id).first()
    right_source = db.query(SourceSystem).filter_by(id=payload.source_right_id).first()
    if left_source is None or right_source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source system not found for left/right ledger",
        )

    left_records = _read_ledger_records(db, payload.source_left_id, start_at=start_dt, cutoff_at=cutoff_dt)
    right_records = _read_ledger_records(db, payload.source_right_id, start_at=start_dt, cutoff_at=cutoff_dt)

    service = ReconciliationService()
    run_result = service.reconcile(
        left_records=left_records,
        right_records=right_records,
        source_left_id=payload.source_left_id,
        source_right_id=payload.source_right_id,
        start_at=start_dt,
        cutoff_at=cutoff_dt,
        currency=payload.currency,
        policy_version=payload.policy_version_id,
        input_checkpoint=payload.input_checkpoint,
    )

    run = ReconciliationRunModel(
        id=run_id,
        source_left_id=payload.source_left_id,
        source_right_id=payload.source_right_id,
        start_at=start_dt,
        cutoff_at=cutoff_dt,
        policy_version_id=payload.policy_version_id,
        input_checkpoint=payload.input_checkpoint,
        status=ReconciliationRunState.COMPLETED,
        created_at=_utc_now(),
    )
    db.add(run)
    db.flush()

    result_rows: list[ReconciliationResultModel] = []
    for index, match in enumerate(run_result.matches, start=1):
        result_rows.append(
            ReconciliationResultModel(
                id=f"{run_id}-{index:04d}",
                run_id=run_id,
                left_record_id=match.left_record_id,
                right_record_id=match.right_record_id,
                status=match.status.value,
                variance_minor=match.variance_minor,
                reason_code=match.reason_code,
            )
        )
    db.add_all(result_rows)
    db.flush()

    run.status = ReconciliationRunState.COMPLETED
    run_results = {
        "MATCHED": 0,
        "AMOUNT_MISMATCH": 0,
        "FIELD_MISMATCH": 0,
        "INTERNAL_ONLY": 0,
        "COUNTERPART_ONLY": 0,
        "PENDING_LATE": 0,
        "AMBIGUOUS": 0,
        "UNBALANCED_JOURNAL": 0,
    }
    for item in run_result.matches:
        run_results[item.status.value] = run_results.get(item.status.value, 0) + 1

    run.total_count = len(run_result.matches)
    run.matched_count = run_results["MATCHED"]
    run.mismatch_count = run_results["AMOUNT_MISMATCH"] + run_results["FIELD_MISMATCH"]
    run.missing_count = run_results["INTERNAL_ONLY"] + run_results["COUNTERPART_ONLY"]
    db.commit()

    response = ReconciliationRun(
        id=run.id,
        source_left_id=run.source_left_id,
        source_right_id=run.source_right_id,
        start_at=run.start_at,
        cutoff_at=run.cutoff_at,
        currency=payload.currency,
        policy_version_id=run.policy_version_id or payload.policy_version_id,
        input_checkpoint=run.input_checkpoint,
        state=ReconciliationRunState.COMPLETED,
        created_at=run.created_at,
        completed_at=_utc_now(),
        total_count=run.total_count,
        matched_count=run.matched_count,
        mismatch_count=run.mismatch_count,
        missing_count=run.missing_count,
    )
    return ApiResponse(data=response, meta={"run_id": run_id}, request_id=req_id)


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
    cursor: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> PaginatedResponse[ReconciliationResult]:
    req_id = getattr(request.state, "request_id", "unknown-request-id")
    stmt = select(ReconciliationResultModel).where(ReconciliationResultModel.run_id == run_id).order_by(ReconciliationResultModel.id.asc())
    if cursor:
        _, result_id = _decode_cursor(cursor)
        stmt = stmt.filter(ReconciliationResultModel.id > result_id)

    rows = db.scalars(stmt.limit(limit + 1)).all()
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = None
    if has_more and page:
        next_cursor = _encode_cursor(run_id, page[-1].id)

    items: list[ReconciliationResult] = []
    for row in page:
        items.append(
            ReconciliationResult(
                id=row.id,
                run_id=row.run_id,
                left_record_id=row.left_record_id,
                right_record_id=row.right_record_id,
                status=row.status,
                variance_minor=row.variance_minor,
                reason_code=row.reason_code,
                left_amount_minor=None,
                right_amount_minor=None,
                created_at=_utc_now(),
            )
        )

    meta = CursorPaginationMeta(next_cursor=next_cursor, has_more=has_more, total_count=len(items), limit=limit)
    return PaginatedResponse(data=tuple(items), meta=meta, request_id=req_id)
