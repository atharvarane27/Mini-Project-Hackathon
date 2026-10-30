"""Shared immutable API/domain primitives for every backend phase."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum, StrEnum
from typing import Annotated, Any, Generic, TypeVar

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
)


StableId = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
]
CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
MinorUnits = Annotated[int, Field(strict=True, ge=0)]
PositiveMinorUnits = Annotated[int, Field(strict=True, gt=0)]


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(UTC)


UtcDateTime = Annotated[datetime, AfterValidator(_as_utc)]


class FrozenContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class OutboxStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PUBLISHED = "PUBLISHED"
    DEAD_LETTER = "DEAD_LETTER"


class OutboxEventContract(FrozenContract):
    event_id: StableId
    event_type: StableId
    entity_id: StableId
    entity_version: int = Field(strict=True, ge=1)
    payload: Mapping[str, Any]
    payload_hash: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    status: OutboxStatus
    attempt_count: int = Field(strict=True, ge=0)
    created_at: UtcDateTime


class PaginationMeta(FrozenContract):
    offset: int = Field(strict=True, ge=0)
    limit: int = Field(strict=True, ge=1, le=500)
    total: int = Field(strict=True, ge=0)


class ErrorDetail(FrozenContract):
    code: StableId
    message: Annotated[str, StringConstraints(min_length=1, max_length=500)]
    details: Mapping[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(FrozenContract):
    error: ErrorDetail
    request_id: StableId


DataT = TypeVar("DataT")


class DataEnvelope(FrozenContract, Generic[DataT]):
    data: DataT
    meta: Mapping[str, Any] = Field(default_factory=dict)
    request_id: StableId


def _canonical(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        raise TypeError("floating-point values are forbidden in fingerprints")
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return _as_utc(value).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return _canonical(value.value)
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("fingerprint object keys must be strings")
        return {key: _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, BaseModel):
        return _canonical(value.model_dump(mode="python"))
    raise TypeError(f"unsupported fingerprint value {type(value).__name__}")


def deterministic_fingerprint(namespace: str, payload: object) -> str:
    normalized_namespace = namespace.strip()
    if not normalized_namespace:
        raise ValueError("fingerprint namespace must not be empty")
    encoded = json.dumps(
        {"namespace": normalized_namespace, "payload": _canonical(payload)},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(encoded.encode()).hexdigest()
