"""Ingestion job response contracts."""

from pydantic import Field

from app.schemas.common import FrozenContract, StableId


class IngestionJobContract(FrozenContract):
    job_id: StableId
    status: str
    source_system: StableId
    source_file: StableId
    file_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    last_row_number: int = Field(strict=True, ge=1)
    processed_count: int = Field(strict=True, ge=0)
    accepted_count: int = Field(strict=True, ge=0)
    rejected_count: int = Field(strict=True, ge=0)
    duplicate_count: int = Field(strict=True, ge=0)
    failure_message: str | None = None
