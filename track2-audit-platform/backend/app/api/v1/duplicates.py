"""Read-only duplicate comparison evidence endpoint."""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Header, Query

from app.engines.identity.resolver import (
    DuplicateClassification,
    DuplicateRepository,
)


def create_duplicates_router(repository: DuplicateRepository) -> APIRouter:
    router = APIRouter()

    @router.get("/duplicates")
    def list_duplicates(
        classification: DuplicateClassification | None = Query(default=None),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
        request_id_header: str | None = Header(default=None, alias="X-Request-ID"),
    ) -> dict[str, object]:
        items = repository.list(
            classification=classification,
            offset=offset,
            limit=limit,
        )
        return {
            "data": [item.as_dict() for item in items],
            "meta": {
                "offset": offset,
                "limit": limit,
                "returned": len(items),
                "classification": classification.value if classification else "ALL",
            },
            "request_id": request_id_header or str(uuid4()),
        }

    return router
