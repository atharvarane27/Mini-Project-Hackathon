import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StrictInt,
    StringConstraints,
)


class UserRole(StrEnum):
    """RBAC roles per PRD section 2."""

    ADMIN = "ADMIN"
    AUDITOR = "AUDITOR"
    REVIEWER = "REVIEWER"
    VIEWER = "VIEWER"
    SYSTEM_WORKER = "SYSTEM_WORKER"


class OutboxStatus(StrEnum):
    """Transactional outbox event lifecycle."""

    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


def ensure_utc_datetime(v: Any) -> datetime:
    """Validate that input is a timezone-aware ISO-8601 UTC datetime."""
    if isinstance(v, str):
        cleaned = v.strip()
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        try:
            v = datetime.fromisoformat(cleaned)
        except Exception as e:
            raise ValueError(f"Malformed ISO-8601 timestamp '{v}': {e}") from e
    if not isinstance(v, datetime) or v.tzinfo is None:
        raise ValueError("Datetime must be an ISO-8601 timezone-aware UTC timestamp")
    return v.astimezone(UTC)


UtcDatetime = Annotated[datetime, BeforeValidator(ensure_utc_datetime)]
CurrencyCode = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Z]{3}$")]
MoneyMinor = StrictInt


def compute_source_record_fingerprint(source_system: str, external_ref: str, revision: int) -> str:
    """Deterministic SHA-256 fingerprint from source_system + external_ref + revision."""
    canonical_repr = f"{source_system.strip().upper()}:{external_ref.strip()}:{revision}"
    return hashlib.sha256(canonical_repr.encode("utf-8")).hexdigest()


def compute_finding_fingerprint(finding_type: str, *keys: str | int) -> str:
    """Deterministic SHA-256 fingerprint for finding deduplication."""
    canonical_repr = ":".join([finding_type.strip().upper()] + [str(k).strip() for k in keys])
    return hashlib.sha256(canonical_repr.encode("utf-8")).hexdigest()


class ApiResponse[T](BaseModel):
    """Standard success envelope matching PRD section 7 conventions."""

    model_config = ConfigDict(frozen=True)

    data: T
    meta: dict[str, Any] = Field(default_factory=dict)
    request_id: str


class CursorPaginationMeta(BaseModel):
    """Cursor-based pagination metadata."""

    model_config = ConfigDict(frozen=True)

    next_cursor: str | None = None
    has_more: bool = False
    total_count: int | None = None
    limit: int = 50


class PaginatedResponse[T](BaseModel):
    """Paginated collection response."""

    model_config = ConfigDict(frozen=True)

    data: tuple[T, ...]
    meta: CursorPaginationMeta
    request_id: str


class ApiErrorDetail(BaseModel):
    """Structured error payload details."""

    model_config = ConfigDict(frozen=True)

    code: str
    message: str
    details: dict[str, Any] | Sequence[Any] | None = None


class ApiErrorResponse(BaseModel):
    """Standard error envelope matching PRD section 7 conventions."""

    model_config = ConfigDict(frozen=True)

    error: ApiErrorDetail
    request_id: str


class HealthStatus(BaseModel):
    """Health check response payload."""

    model_config = ConfigDict(frozen=True)

    status: str = "ok"
    app: str
    version: str
    timestamp: str
    db_backend: str


class OutboxEvent(BaseModel):
    """Durable outbox record representation."""

    model_config = ConfigDict(frozen=True)

    id: str
    event_type: str
    entity_id: str
    payload_json: dict[str, Any]
    status: OutboxStatus = OutboxStatus.PENDING
    attempt_count: StrictInt = 0
    created_at: UtcDatetime
    claimed_at: UtcDatetime | None = None
