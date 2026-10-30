"""P03 bounded streaming, idempotency, quarantine, and restart tests."""

from __future__ import annotations

import hashlib
from io import StringIO

import pytest
from fastapi.testclient import TestClient

from app.ingestion.csv_reader import stream_csv_batches
from app.ingestion.normalizer import DiagnosticCode, REQUIRED_COLUMNS
from app.ingestion.service import (
    InMemoryIngestionRepository,
    IngestionIdempotencyConflict,
    IngestionService,
    IngestionStatus,
)
from app.main import create_app


HEADER = (
    "external_id,transaction_reference,sender_account_id,receiver_account_id,"
    "amount,currency,occurred_at,revision,direction\n"
)


def csv_text(count: int, *, malformed_at: int | None = None) -> str:
    rows = [HEADER]
    for index in range(count):
        amount = "bad" if index == malformed_at else "1250.50"
        rows.append(
            f"EXT-{index},TXN-{index},A-{index % 10},B-{index % 10},{amount},"
            f"INR,2026-10-30T08:00:00Z,1,DEBIT\n"
        )
    return "".join(rows)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def test_reader_never_yields_more_than_configured_batch() -> None:
    batches = list(
        stream_csv_batches(
            StringIO(csv_text(1_203)),
            required_columns=REQUIRED_COLUMNS,
            batch_size=200,
        )
    )
    assert max(map(len, batches)) == 200
    assert sum(map(len, batches)) == 1_203


def test_more_than_10k_rows_ingest_in_bounded_batches() -> None:
    content = csv_text(10_005)
    repository = InMemoryIngestionRepository()
    job = IngestionService(repository, batch_size=250).ingest(
        StringIO(content), source_system="ledger", source_file="large.csv",
        file_hash=digest(content), idempotency_key="large-import-001",
    )
    assert job.status is IngestionStatus.COMPLETED
    assert job.processed_count == job.accepted_count == 10_005
    assert len(repository.accepted()) == 10_005


def test_invalid_rows_are_quarantined_and_job_remains_queryable() -> None:
    content = csv_text(5, malformed_at=2)
    repository = InMemoryIngestionRepository()
    job = IngestionService(repository, batch_size=2).ingest(
        StringIO(content), source_system="ledger", source_file="mixed.csv",
        file_hash=digest(content), idempotency_key="mixed-import-001",
    )
    assert (job.accepted_count, job.rejected_count) == (4, 1)
    assert repository.get(job.job_id) == job
    assert repository.errors(job.job_id)[0].diagnostic.code is DiagnosticCode.INVALID_AMOUNT


def test_repeat_file_creates_no_duplicate_source_identity() -> None:
    content = csv_text(10)
    repository = InMemoryIngestionRepository()
    service = IngestionService(repository)
    first = service.ingest(
        StringIO(content), source_system="ledger", source_file="repeat.csv",
        file_hash=digest(content), idempotency_key="repeat-import-001",
    )
    replay = service.ingest(
        StringIO(content), source_system="ledger", source_file="repeat.csv",
        file_hash=digest(content), idempotency_key="repeat-import-002",
    )
    assert first.accepted_count == 10
    assert replay.duplicate_count == 10
    assert len(repository.accepted()) == 10


def test_interrupted_job_resumes_after_last_committed_batch() -> None:
    content = csv_text(12)
    repository = InMemoryIngestionRepository()
    service = IngestionService(repository, batch_size=5)
    with pytest.raises(RuntimeError, match="interruption"):
        service.ingest(
            StringIO(content), source_system="ledger", source_file="resume.csv",
            file_hash=digest(content), idempotency_key="resume-import-001",
            fail_after_batches=1,
        )
    failed = next(job for job in repository._jobs.values())  # noqa: SLF001
    assert failed.status is IngestionStatus.FAILED
    completed = service.ingest(
        StringIO(content), source_system="ledger", source_file="resume.csv",
        file_hash=digest(content), idempotency_key="resume-import-001",
    )
    assert completed.status is IngestionStatus.COMPLETED
    assert completed.processed_count == completed.accepted_count == 12


def test_changed_file_under_same_idempotency_key_is_conflict() -> None:
    repository = InMemoryIngestionRepository()
    service = IngestionService(repository)
    first = csv_text(1)
    service.ingest(
        StringIO(first), source_system="ledger", source_file="one.csv",
        file_hash=digest(first), idempotency_key="conflict-import-001",
    )
    changed = csv_text(2)
    with pytest.raises(IngestionIdempotencyConflict):
        service.ingest(
            StringIO(changed), source_system="ledger", source_file="one.csv",
            file_hash=digest(changed), idempotency_key="conflict-import-001",
        )


def test_ingestion_api_upload_and_status() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/ingestion/jobs",
        files={"file": ("upload.csv", csv_text(3), "text/csv")},
        data={"source_system": "ledger"},
        headers={"Idempotency-Key": "upload-import-001"},
    )
    assert response.status_code == 202
    job_id = response.json()["data"]["job_id"]
    status_response = client.get(f"/api/v1/ingestion/jobs/{job_id}")
    assert status_response.status_code == 200
    assert status_response.json()["data"]["accepted_count"] == 3
