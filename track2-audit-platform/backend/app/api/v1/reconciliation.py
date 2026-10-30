"""Composable reconciliation run and result endpoints."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Header, Query
from fastapi.responses import JSONResponse

from app.engines.reconciliation.journal_balance import ReconciliationJournalLine
from app.engines.reconciliation.matcher import LedgerEntry, ReconciliationPolicy
from app.engines.reconciliation.service import (
    ReconciliationRepository,
    ReconciliationRunConflict,
    run_reconciliation,
)
from app.schemas.reconciliation import ReconciliationRunRequest


LedgerLoader = Callable[[str, datetime, datetime, str], Iterable[LedgerEntry]]
JournalLoader = Callable[[str, str, datetime, datetime, str], Iterable[ReconciliationJournalLine]]
PolicyLoader = Callable[[int], ReconciliationPolicy]


def create_reconciliation_router(
    *,
    repository: ReconciliationRepository,
    load_ledger: LedgerLoader,
    load_journals: JournalLoader,
    load_policy: PolicyLoader,
) -> APIRouter:
    router = APIRouter()

    @router.post("/reconciliation/runs", status_code=202, response_model=None)
    def create_run(
        request: ReconciliationRunRequest,
        request_id: str | None = Header(default=None, alias="X-Request-ID"),
    ) -> dict[str, object] | JSONResponse:
        identifier = request_id or str(uuid4())
        try:
            policy = load_policy(request.policy_version)
        except KeyError as error:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "POLICY_NOT_FOUND", "message": str(error)}, "request_id": identifier},
            )
        left = load_ledger(request.left_source_id, request.start_at, request.end_at, request.snapshot_checkpoint)
        right = load_ledger(request.right_source_id, request.start_at, request.end_at, request.snapshot_checkpoint)
        journals = load_journals(
            request.left_source_id, request.right_source_id,
            request.start_at, request.end_at, request.snapshot_checkpoint,
        )
        try:
            outcome = run_reconciliation(
                left_source_id=request.left_source_id,
                right_source_id=request.right_source_id,
                left_entries=left,
                right_entries=right,
                journal_lines=journals,
                cutoff_at=request.cutoff_at,
                checkpoint=request.snapshot_checkpoint,
                policy=policy,
                repository=repository,
            )
        except ReconciliationRunConflict as error:
            return JSONResponse(
                status_code=409,
                content={"error": {"code": "RUN_INPUT_CONFLICT", "message": str(error)}, "request_id": identifier},
            )
        return {
            "data": {**outcome.run.as_dict(), "replayed": outcome.replayed},
            "meta": {},
            "request_id": identifier,
        }

    @router.get("/reconciliation/runs/{run_id}/results", response_model=None)
    def get_results(
        run_id: str,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
        request_id: str | None = Header(default=None, alias="X-Request-ID"),
    ) -> dict[str, object] | JSONResponse:
        identifier = request_id or str(uuid4())
        run = repository.get_run(run_id)
        if run is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "RECONCILIATION_RUN_NOT_FOUND", "message": "reconciliation run not found"}, "request_id": identifier},
            )
        page = run.results[offset : offset + limit]
        return {
            "data": [item.as_dict() for item in page],
            "meta": {"offset": offset, "limit": limit, "returned": len(page), "total": len(run.results)},
            "request_id": identifier,
        }

    return router
