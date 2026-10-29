"""Pydantic v2 schemas for ingestion jobs and source-record events.

All models are frozen (immutable) per P01 contract specification.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.schemas.common import UtcDatetime


# ---------------------------------------------------------------------------
# Ingestion job lifecycle
# ---------------------------------------------------------------------------


class IngestionJobState(StrEnum):
    """State machine for a CSV import job."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"


class IngestionJobCounts(BaseModel):
    """Running record-level counters for an ingestion job."""

    model_config = ConfigDict(frozen=True)

    total_rows: StrictInt = 0
    accepted: StrictInt = 0
    rejected: StrictInt = 0
    conflict: StrictInt = 0
    pending_review: StrictInt = 0


class IngestionJob(BaseModel):
    """Metadata for a single CSV source import job."""

    model_config = ConfigDict(frozen=True)

    id: str
    source_system_id: str
    state: IngestionJobState = IngestionJobState.PENDING
    counts: IngestionJobCounts = Field(default_factory=IngestionJobCounts)
    errors: tuple[dict[str, Any], ...] = Field(default_factory=tuple)
    started_at: UtcDatetime
    completed_at: UtcDatetime | None = None


class IngestionJobCreate(BaseModel):
    """Request body for POST /ingestion/jobs (form-data / multipart)."""

    model_config = ConfigDict(frozen=True)

    source_system_id: str
    idempotency_key: str | None = None


class IngestionRowError(BaseModel):
    """Per-row validation or parsing error captured during ingestion."""

    model_config = ConfigDict(frozen=True)

    row_number: StrictInt
    external_ref: str | None = None
    error_code: str
    error_message: str
    raw_data: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Inter-service events (Ingestion → Identity / Detectors)
# ---------------------------------------------------------------------------


class SourceRecordEvent(BaseModel):
    """Event emitted after a source record is accepted, for identity matching.

    Maps to PRD section 10 interface contract:
    Ingestion → identity: SourceRecordEvent(source_record_id, normalized_fields,
    canonical_transaction_id?, checkpoint)
    """

    model_config = ConfigDict(frozen=True)

    source_record_id: str
    normalized_fields: dict[str, Any]
    canonical_transaction_id: str | None = None
    checkpoint: str


class CanonicalTransferEvent(BaseModel):
    """Event emitted after canonical transaction is written, for detectors.

    Maps to PRD section 10 interface contract:
    Ingestion → detection: CanonicalTransferEvent(transaction_id, sender,
    receiver, amount_minor, currency, occurred_at, status, checkpoint)
    """

    model_config = ConfigDict(frozen=True)

    transaction_id: str
    sender: str
    receiver: str
    amount_minor: StrictInt
    currency: str
    occurred_at: UtcDatetime
    status: str
    checkpoint: str
