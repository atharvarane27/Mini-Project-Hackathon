"""Scaffold for backend/app/api/v1/duplicates; implementation pending."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.engines.identity.resolver import DuplicateResolver
from app.schemas.common import ApiResponse

router = APIRouter(prefix="/duplicates", tags=["Duplicates"])


def _build_resolver() -> DuplicateResolver:
    return DuplicateResolver(
        index_fields=["payee_name", "amount_minor", "account_id"],
        phonetic_field="payee_name",
        text_field="payee_name",
        amount_field="amount_minor",
        similarity_threshold=0.75,
    )


@router.get(
    "",
    response_model=ApiResponse[list[dict[str, Any]]],
    status_code=status.HTTP_200_OK,
    summary="Return duplicate candidates and classifications derived from the P05 blocking layer and P06 ed-distance rules",
)
def get_duplicates(
    request: Request,
    limit: int = Query(default=25, ge=1, le=200),
    db: Session = Depends(get_db),
) -> ApiResponse[list[dict[str, Any]]]:
    """Return deterministically classified duplicate matches.

    This route does not destroy source records and intentionally exposes only the
    candidate rows produced by the application-owned inverted index and blocking
    layer; the final classification uses bounded edit-distance scoring.
    """
    req_id = getattr(request.state, "request_id", "unknown-request-id")
    resolver = _build_resolver()

    # Minimal in-memory demonstration payload for deterministic, auditable results.
    records = [
        {"record_id": "r1", "payee_name": "John Doe", "amount_minor": 50000, "account_id": "A100", "sender_account_id": "SA1", "receiver_account_id": "RA1"},
        {"record_id": "r2", "payee_name": "Jon Doe", "amount_minor": 50000, "account_id": "A100", "sender_account_id": "SA1", "receiver_account_id": "RA1"},
        {"record_id": "r3", "payee_name": "Alice Smith", "amount_minor": 1000, "account_id": "A101", "sender_account_id": "SA2", "receiver_account_id": "RA2"},
        {"record_id": "r4", "payee_name": "Alice Smith", "amount_minor": -1000, "account_id": "A101", "sender_account_id": "RA2", "receiver_account_id": "SA2"},
    ]

    for record in records:
        resolver.add_record(record["record_id"], record)

    results: list[dict[str, Any]] = []
    for record in records[:limit]:
        classified = resolver.resolve(record["record_id"], record)
        for item in classified:
            results.append(
                {
                    "record_id_a": item.record_id_a,
                    "record_id_b": item.record_id_b,
                    "result": item.result,
                    "evidence": {
                        "compared_attributes": list(item.evidence.compared_attributes),
                        "distance": item.evidence.distance,
                        "score": item.evidence.score,
                        "candidate_record_ids": list(item.evidence.candidate_record_ids),
                        "algorithm_version": item.evidence.algorithm_version,
                        "reason": item.evidence.reason,
                    },
                }
            )

    return ApiResponse(data=results[:limit], meta={"count": len(results), "limit": limit}, request_id=req_id)
