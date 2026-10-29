from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field


class ApiResponse[T](BaseModel):
    """Standard success envelope matching PRD section 7 conventions."""

    data: T
    meta: dict[str, Any] = Field(default_factory=dict)
    request_id: str


class ApiErrorDetail(BaseModel):
    """Structured error payload details."""

    code: str
    message: str
    details: dict[str, Any] | Sequence[Any] | None = None


class ApiErrorResponse(BaseModel):
    """Standard error envelope matching PRD section 7 conventions."""

    error: ApiErrorDetail
    request_id: str


class HealthStatus(BaseModel):
    """Health check response payload."""

    status: str = "ok"
    app: str
    version: str
    timestamp: str
    db_backend: str
