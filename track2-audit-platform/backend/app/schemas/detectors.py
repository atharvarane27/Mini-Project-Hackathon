"""HTTP schemas shared by detector run endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


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
