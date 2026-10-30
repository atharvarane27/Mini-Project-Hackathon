"""HTTP request contracts for case claims and lifecycle transitions."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.services.case_service import CaseState

from .common import FrozenContract, StableId, UtcDateTime


class AuditCaseStatus(StrEnum):
    QUEUED = "QUEUED"
    CLAIMED = "CLAIMED"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"


class WorkflowTaskStatus(StrEnum):
    LOCKED = "LOCKED"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"


class AuditCaseContract(FrozenContract):
    case_id: StableId
    case_code: StableId
    finding_ids: tuple[StableId, ...]
    rule_version_id: StableId
    state: AuditCaseStatus
    priority: int = Field(strict=True, ge=0, le=100)
    row_version: int = Field(strict=True, ge=1)
    assignee_id: StableId | None = None
    lease_until: UtcDateTime | None = None
    created_at: UtcDateTime


class WorkflowTaskContract(FrozenContract):
    workflow_task_id: StableId
    case_id: StableId
    task_key: StableId
    state: WorkflowTaskStatus
    prerequisite_task_ids: tuple[StableId, ...] = ()
    row_version: int = Field(strict=True, ge=1)


class CaseClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    worker_id: str = Field(min_length=1, max_length=120)
    lease_seconds: int = Field(default=300, ge=1, le=3600)


class CaseCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_ids: list[str] = Field(min_length=1, max_length=100)
    rule_version_id: str = Field(default="system-default-v1", min_length=1, max_length=128)
    priority: int = Field(default=50, ge=0, le=100)


class CaseTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    new_state: CaseState
