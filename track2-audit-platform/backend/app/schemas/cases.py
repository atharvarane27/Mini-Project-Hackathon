from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import UtcDatetime


class CaseState(StrEnum):
    """Lifecycle state of an audit review case."""

    QUEUED = "QUEUED"
    CLAIMED = "CLAIMED"
    IN_REVIEW = "IN_REVIEW"
    BLOCKED = "BLOCKED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class TaskState(StrEnum):
    """State of an individual workflow task."""

    PENDING = "PENDING"
    BLOCKED = "BLOCKED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class AuditCase(BaseModel):
    """Investigation case created from rule-evaluated findings."""

    model_config = ConfigDict(frozen=True)

    id: str
    case_code: str
    state: CaseState = CaseState.QUEUED
    priority: int = Field(default=50, description="Priority score between 0 and 100")
    row_version: int = 1
    assignee_id: str | None = None
    lease_until: UtcDatetime | None = None
    created_at: UtcDatetime
    finding_ids: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_priority_range(self) -> "AuditCase":
        if not (0 <= self.priority <= 100):
            raise ValueError(f"Case priority must be between 0 and 100, got {self.priority}")
        if self.row_version < 1:
            raise ValueError(f"Case row_version must be >= 1, got {self.row_version}")
        return self


class WorkflowTask(BaseModel):
    """Task node within an instantiated case workflow DAG."""

    model_config = ConfigDict(frozen=True)

    id: str
    case_id: str
    task_template_id: str
    stable_key: str
    display_name: str
    state: TaskState = TaskState.PENDING
    completed_at: UtcDatetime | None = None
    row_version: int = 1

    @model_validator(mode="after")
    def validate_task_version(self) -> "WorkflowTask":
        if self.row_version < 1:
            raise ValueError(f"Task row_version must be >= 1, got {self.row_version}")
        return self


class CaseTransitionRequest(BaseModel):
    """Request payload to transition case state with optimistic concurrency check."""

    model_config = ConfigDict(frozen=True)

    target_state: CaseState
    expected_row_version: int
    reason: str


class CaseClaimRequest(BaseModel):
    """Request payload to claim a case with optimistic locking."""

    model_config = ConfigDict(frozen=True)

    expected_row_version: int
