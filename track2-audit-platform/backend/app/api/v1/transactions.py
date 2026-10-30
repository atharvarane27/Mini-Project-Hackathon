"""Canonical transaction list/search endpoint."""

from __future__ import annotations

from typing import Protocol
from uuid import uuid4

from fastapi import APIRouter, Header, Query

from app.ingestion.canonicalizer import CanonicalTransfer


class TransactionReader(Protocol):
    def list_transactions(
        self,
        *,
        account_id: str | None = None,
        reference: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[CanonicalTransfer, ...]: ...


def create_transactions_router(repository: TransactionReader) -> APIRouter:
    router = APIRouter()

    @router.get("/transactions")
    def list_transactions(
        account_id: str | None = Query(default=None),
        reference: str | None = Query(default=None),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
        request_id_header: str | None = Header(default=None, alias="X-Request-ID"),
    ) -> dict[str, object]:
        items = repository.list_transactions(
            account_id=account_id,
            reference=reference,
            offset=offset,
            limit=limit,
        )
        return {
            "data": [item.as_dict() for item in items],
            "meta": {"offset": offset, "limit": limit, "returned": len(items)},
            "request_id": request_id_header or str(uuid4()),
        }

    return router
