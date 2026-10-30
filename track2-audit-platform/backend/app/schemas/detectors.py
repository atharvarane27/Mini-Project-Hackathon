"""HTTP schemas shared by detector run endpoints."""

from __future__ import annotations

from datetime import datetime
from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from .common import FrozenContract, StableId, UtcDateTime


class FindingType(StrEnum):
    DUPLICATE_CANDIDATE = "DUPLICATE_CANDIDATE"
    RECONCILIATION_MISMATCH = "RECONCILIATION_MISMATCH"
    CIRCULAR_FLOW = "CIRCULAR_FLOW"
    SPLITTING_PATTERN = "SPLITTING_PATTERN"


FINDING_FACT_NAMES = frozenset(
    {
        "Similarity_Score",
        "Reconciliation_Variance_Minor",
        "Allowed_Variance_Minor",
        "Balance_Anomaly_Flag",
        "Circular_Flow_Detected",
        "Cycle_Length",
        "Cycle_Duration_Minutes",
        "Initial_Amount_Minor",
        "Minimum_Amount_Minor",
        "Maximum_Amount_Minor",
        "Splitting_Window_Sum_Minor",
        "Splitting_Window_Count",
        "Splitting_Window_Duration_Minutes",
        "Splitting_Threshold_Minor",
        "Transaction_Velocity",
    }
)


class FindingContract(FrozenContract):
    finding_id: StableId
    finding_type: FindingType
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    transaction_ids: tuple[StableId, ...]
    facts: Mapping[str, Any]
    evidence: Mapping[str, Any]
    detector_config_version: int = Field(strict=True, ge=1)
    algorithm_version: StableId
    status: StableId = "FLAGGED_FOR_REVIEW"
    created_at: UtcDateTime

    @model_validator(mode="after")
    def validate_identity(self) -> FindingContract:
        if not self.transaction_ids or len(set(self.transaction_ids)) != len(
            self.transaction_ids
        ):
            raise ValueError("transaction_ids must be non-empty and unique")
        unknown = set(self.facts) - FINDING_FACT_NAMES
        if unknown:
            raise ValueError(f"unknown finding fact names: {sorted(unknown)}")
        return self


class SplittingRunRequest(BaseModel):
    """Stable-snapshot request for a P11 splitting detector run."""

    model_config = ConfigDict(extra="forbid")

    start_at: AwareDatetime
    end_at: AwareDatetime
    policy_version: int = Field(gt=0)
    snapshot_checkpoint: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_range(self) -> SplittingRunRequest:
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        if not self.snapshot_checkpoint.strip():
            raise ValueError("snapshot_checkpoint must not be blank")
        self.snapshot_checkpoint = self.snapshot_checkpoint.strip()
        return self

    @property
    def normalized_start(self) -> datetime:
        return self.start_at

    @property
    def normalized_end(self) -> datetime:
        return self.end_at


class CircularRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_at: AwareDatetime
    end_at: AwareDatetime
    policy_version: int = Field(gt=0)
    snapshot_checkpoint: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_range(self) -> CircularRunRequest:
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        self.snapshot_checkpoint = self.snapshot_checkpoint.strip()
        if not self.snapshot_checkpoint:
            raise ValueError("snapshot_checkpoint must not be blank")
        return self
