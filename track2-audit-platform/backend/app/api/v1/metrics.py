"""Small operational snapshot for the composed API runtime."""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Header

from app.runtime import RuntimeServices


def create_metrics_router(runtime: RuntimeServices) -> APIRouter:
    router = APIRouter()

    @router.get("/metrics")
    def metrics(
        request_id: str | None = Header(default=None, alias="X-Request-ID"),
    ) -> dict[str, object]:
        case_repository = runtime.cases.repository
        return {
            "data": {
                "ingestion_source_records": len(runtime.ingestion_repository.accepted()),
                "canonical_transactions": len(runtime.canonical.downstream_snapshot()),
                "duplicate_evidence": len(runtime.duplicates.list(limit=500)),
                "circular_findings": runtime.circular.finding_count,
                "splitting_findings": runtime.splitting.finding_count,
                "case_count": len(case_repository.list_cases()),
                "activity_count": len(runtime.activity.list()),
            },
            "meta": {},
            "request_id": request_id or str(uuid4()),
        }

    return router
