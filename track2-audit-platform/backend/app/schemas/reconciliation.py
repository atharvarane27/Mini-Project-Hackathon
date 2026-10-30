"""Validated API contracts for reconciliation runs."""

from __future__ import annotations

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class ReconciliationRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    left_source_id: str = Field(min_length=1, max_length=128)
    right_source_id: str = Field(min_length=1, max_length=128)
    start_at: AwareDatetime
    end_at: AwareDatetime
    cutoff_at: AwareDatetime
    policy_version: int = Field(gt=0)
    snapshot_checkpoint: str = Field(min_length=1, max_length=256)

    @model_validator(mode="after")
    def validate_request(self) -> "ReconciliationRunRequest":
        self.left_source_id = self.left_source_id.strip()
        self.right_source_id = self.right_source_id.strip()
        self.snapshot_checkpoint = self.snapshot_checkpoint.strip()
        if not self.left_source_id or not self.right_source_id:
            raise ValueError("source IDs must not be blank")
        if self.left_source_id == self.right_source_id:
            raise ValueError("left and right source IDs must differ")
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        if self.cutoff_at < self.start_at:
            raise ValueError("cutoff_at must not be before start_at")
        if not self.snapshot_checkpoint:
            raise ValueError("snapshot_checkpoint must not be blank")
        return self
