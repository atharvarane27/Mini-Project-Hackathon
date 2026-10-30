"""Stable public error codes and envelope construction."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from app.schemas.common import ErrorDetail, ErrorEnvelope


class ErrorCode(StrEnum):
    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    CONFLICT = "CONFLICT"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


def error_envelope(
    code: ErrorCode,
    message: str,
    request_id: str,
    details: Mapping[str, Any] | None = None,
) -> ErrorEnvelope:
    return ErrorEnvelope(
        error=ErrorDetail(
            code=code.value,
            message=message,
            details={} if details is None else dict(details),
        ),
        request_id=request_id,
    )
