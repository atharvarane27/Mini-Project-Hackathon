"""Pydantic v2 schemas for reconciliation runs and results.

All models are frozen (immutable) per P01 contract specification.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from app.schemas.common import MoneyMinor, UtcDatetime


# ---------------------------------------------------------------------------
# Reconciliation run enums
# ---------------------------------------------------------------------------


class ReconciliationRunState(StrEnum):
    """Lifecycle state of a reconciliation run job."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ReconciliationMatchStatus(StrEnum):
    """Per-record match outcome produced by the reconciliation matcher."""

    MATCHED = "MATCHED"
    MISSING_LEFT = "MISSING_LEFT"
    MISSING_RIGHT = "MISSING_RIGHT"
    MISMATCH = "MISMATCH"
    AMBIGUOUS = "AMBIGUOUS"
    WITHIN_TOLERANCE = "WITHIN_TOLERANCE"


# ---------------------------------------------------------------------------
# Reconciliation run
# ---------------------------------------------------------------------------


class ReconciliationRunCreate(BaseModel):
    """Request body for POST /reconciliation/runs."""

    model_config = ConfigDict(frozen=True)

    source_left_id: str
    source_right_id: str
    start_at: UtcDatetime
    cutoff_at: UtcDatetime
    policy_version_id: str
    idempotency_key: str | None = None

    @model_validator(mode="after")
    def validate_time_range(self) -> "ReconciliationRunCreate":
        if self.cutoff_at <= self.start_at:
            raise ValueError("cutoff_at must be after start_at")
        return self


class ReconciliationRun(BaseModel):
    """Persisted reconciliation run entity."""

    model_config = ConfigDict(frozen=True)

    id: str
    source_left_id: str
    source_right_id: str
    start_at: UtcDatetime
    cutoff_at: UtcDatetime
    policy_version_id: str
    input_checkpoint: str | None = None
    state: ReconciliationRunState = ReconciliationRunState.PENDING
    created_at: UtcDatetime
    completed_at: UtcDatetime | None = None
    total_count: StrictInt = 0
    matched_count: StrictInt = 0
    mismatch_count: StrictInt = 0
    missing_count: StrictInt = 0


# ---------------------------------------------------------------------------
# Reconciliation result
# ---------------------------------------------------------------------------


class ReconciliationResult(BaseModel):
    """Individual match/mismatch result row for a reconciliation run.

    Maps to reconciliation_results DB table (PRD section 8, schema ERD).
    left_record_id and right_record_id are both NULL for AMBIGUOUS rows where
    no canonical pairing could be determined.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    run_id: str
    left_record_id: str | None = None
    right_record_id: str | None = None
    status: ReconciliationMatchStatus
    variance_minor: MoneyMinor = 0
    reason_code: str
    left_amount_minor: MoneyMinor | None = None
    right_amount_minor: MoneyMinor | None = None
    created_at: UtcDatetime


class ReconciliationPolicy(BaseModel):
    """Tolerance and matching configuration for a reconciliation run."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    version: StrictInt = 1
    tolerance_minor: MoneyMinor = Field(
        default=0,
        description="Absolute variance allowed before flagging as MISMATCH (paise)",
    )
    match_fields: tuple[str, ...] = Field(
        default=("external_ref",),
        description="Ordered list of fields used as match keys",
    )
    is_active: bool = True


# ---------------------------------------------------------------------------
# Reconciliation summary (for dashboard)
# ---------------------------------------------------------------------------


class ReconciliationSummary(BaseModel):
    """Aggregated result counts for a completed reconciliation run."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    matched: StrictInt = 0
    mismatch: StrictInt = 0
    missing_left: StrictInt = 0
    missing_right: StrictInt = 0
    ambiguous: StrictInt = 0
    within_tolerance: StrictInt = 0
    total: StrictInt = 0
    total_variance_minor: MoneyMinor = 0
