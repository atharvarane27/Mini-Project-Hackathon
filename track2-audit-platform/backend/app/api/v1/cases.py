"""Case listing, atomic claim, and versioned transition endpoints."""

from __future__ import annotations

from datetime import timedelta
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Header, Query
from fastapi.responses import JSONResponse

from app.core.audit_writer import ActivityLedger
from app.schemas.cases import CaseClaimRequest, CaseCreateRequest, CaseTransitionRequest
from app.services.case_service import (
    CaseConflictError,
    CaseNotFoundError,
    CaseService,
    InvalidCaseTransitionError,
)


def _request_id(value: str | None) -> str:
    return value.strip() if value and value.strip() else str(uuid4())


def _error(
    status_code: int,
    code: str,
    message: str,
    request_id: str,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {"code": code, "message": message, "details": {}},
            "request_id": request_id,
        },
    )


def create_cases_router(
    service: CaseService,
    ledger: ActivityLedger | None = None,
) -> APIRouter:
    router = APIRouter()

    def record(
        *, actor_id: str, action: str, case: object, request_id: str,
        old_values: dict[str, object], new_values: dict[str, object],
    ) -> None:
        if ledger is None:
            return
        ledger.append(
            actor_id=actor_id,
            action=action,
            object_id=str(getattr(case, "case_id")),
            object_version=int(getattr(case, "row_version")),
            occurred_at=datetime.now(UTC),
            request_id=request_id,
            old_values=old_values,
            new_values=new_values,
        )

    @router.post("/cases", status_code=201, response_model=None)
    def create_case(
        request: CaseCreateRequest,
        request_id_header: str | None = Header(default=None, alias="X-Request-ID"),
        actor_id: str | None = Header(default=None, alias="X-Actor-ID"),
    ) -> dict[str, object] | JSONResponse:
        request_id = _request_id(request_id_header)
        actor = actor_id.strip() if actor_id else "system"
        try:
            case = service.create_from_findings(
                request.finding_ids,
                request.rule_version_id,
                request.priority,
                actor,
            )
        except ValueError as error:
            return _error(422, "INVALID_CASE", str(error), request_id)
        record(
            actor_id=actor, action="CASE_CREATED", case=case,
            request_id=request_id, old_values={}, new_values=case.as_dict(),
        )
        return {"data": case.as_dict(), "meta": {}, "request_id": request_id}

    @router.get("/cases")
    def list_cases(
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
        request_id_header: str | None = Header(default=None, alias="X-Request-ID"),
    ) -> dict[str, object]:
        request_id = _request_id(request_id_header)
        cases = service.list_cases()
        page = cases[offset : offset + limit]
        return {
            "data": [case.as_dict() for case in page],
            "meta": {
                "offset": offset,
                "limit": limit,
                "returned": len(page),
                "total": len(cases),
            },
            "request_id": request_id,
        }

    @router.post("/cases/{case_id}/claim", response_model=None)
    def claim_case(
        case_id: str,
        request: CaseClaimRequest,
        request_id_header: str | None = Header(default=None, alias="X-Request-ID"),
    ) -> dict[str, object] | JSONResponse:
        request_id = _request_id(request_id_header)
        try:
            case = service.claim_direct(
                case_id,
                request.expected_version,
                request.worker_id,
                timedelta(seconds=request.lease_seconds),
            )
        except CaseConflictError as error:
            return _error(409, "CASE_CLAIM_CONFLICT", str(error), request_id)
        except CaseNotFoundError as error:
            return _error(404, "CASE_NOT_FOUND", str(error), request_id)
        record(
            actor_id=request.worker_id, action="CASE_CLAIMED", case=case,
            request_id=request_id, old_values={"state": "QUEUED"},
            new_values=case.as_dict(),
        )
        return {"data": case.as_dict(), "meta": {}, "request_id": request_id}

    @router.post("/cases/{case_id}/transition", response_model=None)
    def transition_case(
        case_id: str,
        request: CaseTransitionRequest,
        request_id_header: str | None = Header(default=None, alias="X-Request-ID"),
        actor_id: str | None = Header(default=None, alias="X-Actor-ID"),
    ) -> dict[str, object] | JSONResponse:
        request_id = _request_id(request_id_header)
        if actor_id is None or not actor_id.strip():
            return _error(401, "UNAUTHENTICATED", "actor is required", request_id)
        try:
            case = service.transition(
                case_id,
                request.expected_version,
                request.new_state,
                actor_id,
            )
        except CaseNotFoundError as error:
            return _error(404, "CASE_NOT_FOUND", str(error), request_id)
        except CaseConflictError as error:
            return _error(409, "CASE_VERSION_CONFLICT", str(error), request_id)
        except InvalidCaseTransitionError as error:
            return _error(409, "INVALID_CASE_TRANSITION", str(error), request_id)
        record(
            actor_id=actor_id, action="CASE_TRANSITIONED", case=case,
            request_id=request_id, old_values={"row_version": request.expected_version},
            new_values=case.as_dict(),
        )
        return {"data": case.as_dict(), "meta": {}, "request_id": request_id}

    return router
