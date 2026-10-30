"""Duplicate resolution API backed by DB records and bounded candidate blocking."""

from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import SourceRecord, Transaction
from app.db.session import get_db
from app.engines.identity.blocking import BlockingEngine
from app.engines.identity.levenshtein import levenshtein_distance, levenshtein_similarity, normalize_text
from app.engines.identity.resolver import DuplicateResolver
from app.ingestion.canonicalizer import Canonicalizer
from app.schemas.common import ApiResponse, CursorPaginationMeta, PaginatedResponse

router = APIRouter(prefix="/duplicates", tags=["Duplicates"])
canonicalizer = Canonicalizer()


def _encode_cursor(record_id: str, pair_key: str) -> str:
    raw = f"{record_id}|{pair_key}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("utf-8")).decode("utf-8")
        record_id, pair_key = raw.split("|", 1)
        return record_id, pair_key
    except Exception as exc:  # pragma: no cover - defensive API guard
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid duplicate cursor: {exc}",
        ) from exc


def _record_to_identity_fields(txn: Transaction) -> dict[str, Any]:
    return {
        "record_id": txn.id,
        "amount_minor": txn.amount_minor,
        "currency": txn.currency,
        "sender_account_id": txn.sender_account_id,
        "receiver_account_id": txn.receiver_account_id,
        "occurred_at": txn.occurred_at,
        "posted_at": txn.posted_at,
        "payee_name": txn.external_canonical_ref or txn.id,
    }


def _build_resolver() -> DuplicateResolver:
    return DuplicateResolver(
        index_fields=["payee_name", "amount_minor", "sender_account_id", "receiver_account_id"],
        phonetic_field="payee_name",
        text_field="payee_name",
        amount_field="amount_minor",
        similarity_threshold=0.75,
        ambiguous_threshold=0.55,
        max_distance=3,
    )


def _iter_candidate_rows(db: Session, limit: int, cursor: str | None) -> tuple[list[dict[str, Any]], str | None, bool]:
    stmt = select(Transaction).order_by(Transaction.occurred_at.asc(), Transaction.id.asc())
    if cursor:
        last_record_id, _last_pair = _decode_cursor(cursor)
        stmt = stmt.filter(Transaction.id > last_record_id)

    rows = db.scalars(stmt.limit(limit + 1)).all()
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = None
    if has_more and page:
        next_cursor = _encode_cursor(page[-1].id, hashlib.sha256(page[-1].id.encode("utf-8")).hexdigest())
    return [
        {
            "record_id": txn.id,
            "payee_name": txn.external_canonical_ref or txn.id,
            "amount_minor": txn.amount_minor,
            "sender_account_id": txn.sender_account_id,
            "receiver_account_id": txn.receiver_account_id,
        }
        for txn in page
    ], next_cursor, has_more


@router.get(
    "",
    response_model=PaginatedResponse[dict[str, Any]],
    status_code=status.HTTP_200_OK,
    summary="Return duplicate candidates derived from canonical transactions and bounded resolver comparisons",
)
def get_duplicates(
    request: Request,
    limit: int = Query(default=25, ge=1, le=200),
    cursor: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> PaginatedResponse[dict[str, Any]]:
    """Return candidate duplicates from the DB using the bounded identity blocking/resolution pipeline."""
    req_id = getattr(request.state, "request_id", f"req-{uuid.uuid4().hex[:12]}")

    resolver = _build_resolver()
    rows, next_cursor, has_more = _iter_candidate_rows(db, limit, cursor)
    if not rows:
        return PaginatedResponse(
            data=(),
            meta=CursorPaginationMeta(next_cursor=None, has_more=False, total_count=0, limit=limit),
            request_id=req_id,
        )

    for row in rows:
        resolver.add_record(row["record_id"], row)

    items: list[dict[str, Any]] = []
    for row in rows:
        classified = resolver.resolve(row["record_id"], row)
        for item in classified:
            if item.record_id_a == item.record_id_b:
                continue
            items.append(
                {
                    "record_id_a": item.record_id_a,
                    "record_id_b": item.record_id_b,
                    "result": item.result,
                    "soundex_code": item.soundex_code,
                    "levenshtein_distance": item.levenshtein_distance,
                    "similarity_ratio": item.similarity_ratio,
                    "amount_match": item.amount_match,
                    "resolution_reason": item.resolution_reason,
                    "matching_account_keys": list(item.matching_account_keys),
                    "amount_minor": item.amount_minor,
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

    meta = CursorPaginationMeta(
        next_cursor=next_cursor,
        has_more=has_more,
        total_count=len(items),
        limit=limit,
    )
    return PaginatedResponse(data=tuple(items[:limit]), meta=meta, request_id=req_id)
