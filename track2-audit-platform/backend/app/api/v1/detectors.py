"""Composable P11 detector routes.

The P00 application can include the returned router after supplying durable
policy, transfer-snapshot, and repository adapters.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Query, status

from app.engines.circular.service import (
    CircularRunInputConflict,
    CircularRunRepository,
    run_circular_detector,
)
from app.engines.circular.temporal_validator import CircularPolicy, CycleCandidate
from app.engines.splitting.partition import SplittingPolicy, TransferEvent
from app.engines.splitting.service import (
    RunInputConflict,
    SplittingRunRepository,
    run_splitting_detector,
)
from app.schemas.detectors import CircularRunRequest, SplittingRunRequest


PolicyLoader = Callable[[int], SplittingPolicy]
TransferLoader = Callable[[datetime, datetime, str], Iterable[TransferEvent]]
CircularPolicyLoader = Callable[[int], CircularPolicy]
CycleCandidateLoader = Callable[[datetime, datetime, str], Iterable[CycleCandidate]]


def _request_id(value: str | None) -> str:
    return value.strip() if value and value.strip() else str(uuid4())


def create_splitting_router(
    *,
    repository: SplittingRunRepository,
    load_policy: PolicyLoader,
    load_transfers: TransferLoader,
) -> APIRouter:
    """Build routes without module-global database state."""

    router = APIRouter()

    @router.post(
        "/detectors/splitting/runs",
        status_code=status.HTTP_202_ACCEPTED,
    )
    def start_splitting_run(
        request: SplittingRunRequest,
        request_id_header: str | None = Header(default=None, alias="X-Request-ID"),
    ) -> dict[str, object]:
        request_id = _request_id(request_id_header)
        try:
            policy = load_policy(request.policy_version)
        except KeyError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "POLICY_NOT_FOUND", "message": str(error)},
            ) from error

        transfers = load_transfers(
            request.normalized_start,
            request.normalized_end,
            request.snapshot_checkpoint,
        )
        try:
            outcome = run_splitting_detector(
                transfers,
                policy,
                request.snapshot_checkpoint,
                repository,
            )
        except RunInputConflict as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "RUN_INPUT_CONFLICT", "message": str(error)},
            ) from error

        run = outcome.run
        return {
            "data": {
                "run_id": run.run_id,
                "status": run.status,
                "snapshot_checkpoint": run.checkpoint,
                "policy_version": run.policy_version,
                "finding_ids": [finding.finding_id for finding in run.findings],
                "finding_count": len(run.findings),
                "replayed": outcome.replayed,
            },
            "meta": {},
            "request_id": request_id,
        }

    @router.get("/findings")
    def list_findings(
        finding_type: str | None = Query(default=None),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
        request_id_header: str | None = Header(default=None, alias="X-Request-ID"),
    ) -> dict[str, object]:
        request_id = _request_id(request_id_header)
        findings = repository.list_findings(
            finding_type=finding_type,
            offset=offset,
            limit=limit,
        )
        return {
            "data": [finding.as_dict() for finding in findings],
            "meta": {
                "offset": offset,
                "limit": limit,
                "returned": len(findings),
                "filter": finding_type or "ALL",
            },
            "request_id": request_id,
        }

    return router


def create_circular_router(
    *,
    repository: CircularRunRepository,
    load_policy: CircularPolicyLoader,
    load_candidates: CycleCandidateLoader,
) -> APIRouter:
    router = APIRouter()

    @router.post("/detectors/circular/runs", status_code=status.HTTP_202_ACCEPTED)
    def start_circular_run(
        request: CircularRunRequest,
        request_id_header: str | None = Header(default=None, alias="X-Request-ID"),
    ) -> dict[str, object]:
        request_id = _request_id(request_id_header)
        try:
            policy = load_policy(request.policy_version)
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail={"code": "POLICY_NOT_FOUND", "message": str(error)},
            ) from error
        candidates = load_candidates(
            request.start_at, request.end_at, request.snapshot_checkpoint
        )
        try:
            outcome = run_circular_detector(
                candidates, policy, request.snapshot_checkpoint, repository
            )
        except CircularRunInputConflict as error:
            raise HTTPException(
                status_code=409,
                detail={"code": "RUN_INPUT_CONFLICT", "message": str(error)},
            ) from error
        return {
            "data": {
                "run_id": outcome.run.run_id,
                "status": outcome.run.status,
                "snapshot_checkpoint": outcome.run.checkpoint,
                "policy_version": outcome.run.policy_version,
                "finding_ids": [item.finding_id for item in outcome.run.findings],
                "finding_count": len(outcome.run.findings),
                "replayed": outcome.replayed,
            },
            "meta": {},
            "request_id": request_id,
        }

    @router.get("/findings")
    def list_circular_findings(
        finding_type: str | None = Query(default=None),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
        request_id_header: str | None = Header(default=None, alias="X-Request-ID"),
    ) -> dict[str, object]:
        findings = repository.list_findings(
            finding_type=finding_type, offset=offset, limit=limit
        )
        return {
            "data": [item.as_dict() for item in findings],
            "meta": {"offset": offset, "limit": limit, "returned": len(findings)},
            "request_id": _request_id(request_id_header),
        }

    return router
