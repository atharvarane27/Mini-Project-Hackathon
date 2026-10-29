"""HTTP request contracts for case claims and lifecycle transitions."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.services.case_service import CaseState


class CaseClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    worker_id: str = Field(min_length=1, max_length=120)
    lease_seconds: int = Field(default=300, ge=1, le=3600)


class CaseTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    new_state: CaseState
