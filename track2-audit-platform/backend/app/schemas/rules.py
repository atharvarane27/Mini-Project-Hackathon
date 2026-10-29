"""HTTP schemas for rule validation and later rule lifecycle phases."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RuleValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expression: str


class RuleCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    expression: str
