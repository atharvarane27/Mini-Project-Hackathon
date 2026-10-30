"""Restart-safe bounded ingestion jobs with row-level quarantine."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from enum import StrEnum
from threading import Lock
from typing import TextIO
from uuid import NAMESPACE_URL, uuid5

from app.core.idempotency import normalize_idempotency_key
from app.ingestion.canonicalizer import AcceptedSourceTransfer

from .csv_reader import CsvRow, stream_csv_batches
from .normalizer import DiagnosticCode, REQUIRED_COLUMNS, RowDiagnostic, normalize_row


class IngestionStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class IngestionIdempotencyConflict(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class QuarantinedRow:
    row_number: int
    diagnostic: RowDiagnostic
    raw_payload: dict[str, str]


@dataclass(frozen=True, slots=True)
class StoredSourceTransfer:
    transfer: AcceptedSourceTransfer
    source_file: str
    row_number: int
    raw_payload_hash: str
    raw_payload: dict[str, str]


@dataclass(frozen=True, slots=True)
class IngestionJob:
    job_id: str
    idempotency_key: str
    request_hash: str
    source_system: str
    source_file: str
    file_hash: str
    status: IngestionStatus
    last_row_number: int = 1
    processed_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    duplicate_count: int = 0
    failure_message: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id, "status": self.status.value,
            "source_system": self.source_system, "source_file": self.source_file,
            "file_hash": self.file_hash, "last_row_number": self.last_row_number,
            "processed_count": self.processed_count,
            "accepted_count": self.accepted_count,
            "rejected_count": self.rejected_count,
            "duplicate_count": self.duplicate_count,
            "failure_message": self.failure_message,
        }


def raw_payload_hash(values: dict[str, str]) -> str:
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


class InMemoryIngestionRepository:
    def __init__(self) -> None:
        self._lock = Lock()
        self._jobs: dict[str, IngestionJob] = {}
        self._job_ids_by_key: dict[str, str] = {}
        self._sources: dict[tuple[str, str, int], StoredSourceTransfer] = {}
        self._errors: dict[str, list[QuarantinedRow]] = {}

    def start_job(
        self, idempotency_key: str, source_system: str, source_file: str, file_hash: str
    ) -> tuple[IngestionJob, bool]:
        request_hash = hashlib.sha256(
            f"{source_system}|{source_file}|{file_hash}".encode()
        ).hexdigest()
        with self._lock:
            existing_id = self._job_ids_by_key.get(idempotency_key)
            if existing_id is not None:
                existing = self._jobs[existing_id]
                if existing.request_hash != request_hash:
                    raise IngestionIdempotencyConflict(
                        "idempotency key was used for a different file"
                    )
                return existing, True
            job = IngestionJob(
                str(uuid5(NAMESPACE_URL, f"ingestion:{idempotency_key}")),
                idempotency_key, request_hash, source_system, source_file, file_hash,
                IngestionStatus.RUNNING,
            )
            self._jobs[job.job_id] = job
            self._job_ids_by_key[idempotency_key] = job.job_id
            self._errors[job.job_id] = []
            return job, False

    def save_batch(
        self,
        job_id: str,
        rows: tuple[tuple[CsvRow, AcceptedSourceTransfer | None, RowDiagnostic | None], ...],
    ) -> IngestionJob:
        with self._lock:
            job = self._jobs[job_id]
            accepted = rejected = duplicates = 0
            for row, transfer, diagnostic in rows:
                if diagnostic is not None:
                    self._errors[job_id].append(
                        QuarantinedRow(row.row_number, diagnostic, dict(row.values))
                    )
                    rejected += 1
                    continue
                assert transfer is not None
                key = (transfer.source_system, transfer.external_id, transfer.revision)
                digest = raw_payload_hash(row.values)
                existing = self._sources.get(key)
                if existing is not None:
                    if existing.raw_payload_hash == digest:
                        duplicates += 1
                    else:
                        self._errors[job_id].append(
                            QuarantinedRow(
                                row.row_number,
                                RowDiagnostic(
                                    DiagnosticCode.SOURCE_REVISION_CONFLICT,
                                    "source revision has a changed payload",
                                ),
                                dict(row.values),
                            )
                        )
                        rejected += 1
                    continue
                self._sources[key] = StoredSourceTransfer(
                    transfer, job.source_file, row.row_number, digest, dict(row.values)
                )
                accepted += 1
            updated = replace(
                job,
                status=IngestionStatus.RUNNING,
                last_row_number=rows[-1][0].row_number,
                processed_count=job.processed_count + len(rows),
                accepted_count=job.accepted_count + accepted,
                rejected_count=job.rejected_count + rejected,
                duplicate_count=job.duplicate_count + duplicates,
                failure_message=None,
            )
            self._jobs[job_id] = updated
            return updated

    def finish(self, job_id: str) -> IngestionJob:
        with self._lock:
            job = replace(self._jobs[job_id], status=IngestionStatus.COMPLETED)
            self._jobs[job_id] = job
            return job

    def fail(self, job_id: str, message: str) -> IngestionJob:
        with self._lock:
            job = replace(
                self._jobs[job_id], status=IngestionStatus.FAILED,
                failure_message=message,
            )
            self._jobs[job_id] = job
            return job

    def get(self, job_id: str) -> IngestionJob:
        with self._lock:
            return self._jobs[job_id]

    def errors(self, job_id: str) -> tuple[QuarantinedRow, ...]:
        with self._lock:
            return tuple(self._errors[job_id])

    def accepted(self) -> tuple[StoredSourceTransfer, ...]:
        with self._lock:
            return tuple(self._sources[key] for key in sorted(self._sources))


class IngestionService:
    def __init__(
        self,
        repository: InMemoryIngestionRepository,
        *,
        batch_size: int = 500,
        known_accounts: frozenset[str] | None = None,
        known_branches: frozenset[str] | None = None,
    ) -> None:
        self.repository = repository
        self.batch_size = batch_size
        self.known_accounts = known_accounts
        self.known_branches = known_branches

    def ingest(
        self,
        stream: TextIO,
        *,
        source_system: str,
        source_file: str,
        file_hash: str,
        idempotency_key: str,
        fail_after_batches: int | None = None,
    ) -> IngestionJob:
        key = normalize_idempotency_key(idempotency_key)
        job, replayed = self.repository.start_job(
            key, source_system.strip(), source_file.strip(), file_hash
        )
        if replayed and job.status is IngestionStatus.COMPLETED:
            return job
        completed_batches = 0
        try:
            for batch in stream_csv_batches(
                stream, required_columns=REQUIRED_COLUMNS, batch_size=self.batch_size
            ):
                pending = tuple(row for row in batch if row.row_number > job.last_row_number)
                if not pending:
                    continue
                normalized = []
                for row in pending:
                    row_source_system = row.values.get("source_system", "").strip()
                    result = normalize_row(
                        row.values,
                        source_record_id=f"{job.job_id}:{row.row_number}",
                        source_system=row_source_system or source_system,
                        known_accounts=self.known_accounts,
                        known_branches=self.known_branches,
                    )
                    normalized.append((row, result.transfer, result.diagnostic))
                job = self.repository.save_batch(job.job_id, tuple(normalized))
                completed_batches += 1
                if fail_after_batches == completed_batches:
                    raise RuntimeError("simulated ingestion interruption")
            return self.repository.finish(job.job_id)
        except Exception as error:
            self.repository.fail(job.job_id, str(error))
            raise
