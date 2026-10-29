from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import MoneyMinor, UtcDatetime


class FindingType(StrEnum):
    """Detector finding taxonomy."""

    DUPLICATE_CANDIDATE = "DUPLICATE_CANDIDATE"
    RECONCILIATION_MISMATCH = "RECONCILIATION_MISMATCH"
    CIRCULAR_FLOW = "CIRCULAR_FLOW"
    TRANSACTION_SPLITTING = "TRANSACTION_SPLITTING"
    UNBALANCED_JOURNAL = "UNBALANCED_JOURNAL"


class FindingStatus(StrEnum):
    """Lifecycle status of a detector finding."""

    FLAGGED_FOR_REVIEW = "FLAGGED_FOR_REVIEW"
    IN_REVIEW = "IN_REVIEW"
    RESOLVED = "RESOLVED"
    FALSE_POSITIVE = "FALSE_POSITIVE"


class FindingFacts(BaseModel):
    """Standardized finding facts evaluated by the AST rule engine.

    Field names are strictly frozen per PRD section 5 (M06) and Phase P01 specification.
    """

    model_config = ConfigDict(frozen=True)

    Reconciliation_Variance_Minor: MoneyMinor = 0
    Allowed_Variance_Minor: MoneyMinor = 0
    Balance_Anomaly_Flag: bool = False
    Transaction_Velocity: int = 0
    Circular_Flow_Detected: bool = False
    Cycle_Length: int = 0
    Cycle_Duration_Minutes: int = 0
    Splitting_Window_Sum_Minor: MoneyMinor = 0
    Splitting_Window_Count: int = 0
    Duplicate_Candidate_Flag: bool = False
    Severity: str = "MEDIUM"


class DuplicateEvidence(BaseModel):
    """Evidence payload for duplicate candidate detections."""

    model_config = ConfigDict(frozen=True)

    candidate_source_record_ids: tuple[str, ...]
    matching_account_keys: tuple[str, ...]
    amount_minor: MoneyMinor
    soundex_code: str
    levenshtein_distance: int
    similarity_ratio: float
    resolution_reason: str


class ReconciliationEvidence(BaseModel):
    """Evidence payload for cross-ledger reconciliation exceptions."""

    model_config = ConfigDict(frozen=True)

    left_record_id: str | None = None
    right_record_id: str | None = None
    left_amount_minor: MoneyMinor | None = None
    right_amount_minor: MoneyMinor | None = None
    variance_minor: MoneyMinor
    reconciliation_status: str
    reason_code: str


class CircularFlowEvidence(BaseModel):
    """Evidence payload for time-respecting circular transfer chains."""

    model_config = ConfigDict(frozen=True)

    account_ids: tuple[str, ...]
    transaction_ids: tuple[str, ...]
    timestamps: tuple[UtcDatetime, ...]
    amounts_minor: tuple[MoneyMinor, ...]
    cycle_duration_minutes: int
    cycle_length: int


class SplittingEvidence(BaseModel):
    """Evidence payload for windowed transaction splitting."""

    model_config = ConfigDict(frozen=True)

    sender_account_id: str
    receiver_account_id: str
    window_start: UtcDatetime
    window_end: UtcDatetime
    transaction_ids: tuple[str, ...]
    transaction_amounts_minor: tuple[MoneyMinor, ...]
    window_sum_minor: MoneyMinor
    transaction_count: int


class UnbalancedJournalEvidence(BaseModel):
    """Evidence payload for imbalanced journal entries."""

    model_config = ConfigDict(frozen=True)

    journal_id: str
    branch_id: str
    total_debit_minor: MoneyMinor
    total_credit_minor: MoneyMinor
    imbalance_minor: MoneyMinor
    line_count: int


class FindingDraft(BaseModel):
    """Standardized finding output produced by all detectors before persistence."""

    model_config = ConfigDict(frozen=True)

    finding_type: FindingType
    fingerprint: str
    evidence_json: dict[str, Any]
    transaction_ids: tuple[str, ...] = Field(default_factory=tuple)
    facts: FindingFacts
    detector_config_version: int = 1
    algorithm_version: str


class Finding(BaseModel):
    """Persisted detector finding entity."""

    model_config = ConfigDict(frozen=True)

    id: str
    finding_type: FindingType
    fingerprint: str
    status: FindingStatus = FindingStatus.FLAGGED_FOR_REVIEW
    evidence_json: dict[str, Any]
    transaction_ids: tuple[str, ...] = Field(default_factory=tuple)
    facts: FindingFacts
    detector_config_version: int = 1
    algorithm_version: str
    created_at: UtcDatetime
