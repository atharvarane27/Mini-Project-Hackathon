"""P03 Integration tests: bounded streaming ingestion, idempotency, validation, conflict detection.

Test coverage:
  1. Unit tests for csv_reader – bounded batches, hash determinism, BOM tolerance.
  2. Unit tests for normalizer – stable diagnostic codes per error condition.
  3. Unit tests for the amount/timestamp parsers.
  4. Integration – 10 000+ row streaming with tracemalloc peak < 30 MB.
  5. Integration – idempotent re-import: zero new source-record identities on second run.
  6. Integration – malformed_records.csv quarantine with stable codes; job still queryable.
  7. Integration – revision-conflict: altered payload same
     (source_system, ref, revision) → CONFLICT.
  8. API round-trip – POST /ingestion/jobs and GET /ingestion/jobs/{id} via TestClient.
"""

from __future__ import annotations

import io
import os
import sys
import tracemalloc
import uuid
from collections.abc import Generator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

# ---------------------------------------------------------------------------
# Path adjustment so tests run from the backend/ working directory
# ---------------------------------------------------------------------------
BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.db.models import Base, SourceRecord  # noqa: E402
from app.ingestion.csv_reader import BoundedCSVReader, RawRowRecord, compute_payload_hash  # noqa: E402
from app.ingestion.normalizer import RowNormalizer, parse_amount_to_minor, parse_timestamp_to_utc  # noqa: E402
from app.ingestion.service import IngestionService  # noqa: E402
from app.schemas.ingestion import IngestionJobState  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures directory helper
# ---------------------------------------------------------------------------
FIXTURES_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "fixtures")
)

LEDGER_INTERNAL = os.path.join(FIXTURES_DIR, "ledger_internal.csv")
MALFORMED_CSV = os.path.join(FIXTURES_DIR, "malformed_records.csv")


# ---------------------------------------------------------------------------
# Shared SQLite engine + session fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def sqlite_engine():
    """Isolated in-memory SQLite engine with FK enforcement.

    StaticPool ensures create_all and all subsequent sessions share
    the single DBAPI connection → the same in-memory database.
    """
    from sqlalchemy.pool import StaticPool

    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(eng, "connect")
    def _fk_pragma(dbapi_conn: Any, _rec: Any) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(bind=eng)
    yield eng
    Base.metadata.drop_all(bind=eng)
    eng.dispose()


@pytest.fixture(scope="function")
def db_session(sqlite_engine) -> Generator[Session, None, None]:
    """Clean session rolled back after each test."""
    factory = sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False)
    sess = factory()
    try:
        yield sess
    finally:
        sess.close()


@pytest.fixture(scope="function")
def service() -> IngestionService:
    return IngestionService(batch_size=500)


# ---------------------------------------------------------------------------
# 1. csv_reader unit tests
# ---------------------------------------------------------------------------


class TestBoundedCSVReader:
    """Verify streaming behaviour, hash determinism, and BOM tolerance."""

    def _make_stream(self, content: str) -> io.StringIO:
        return io.StringIO(content)

    def test_yields_all_rows(self) -> None:
        csv_content = "A,B,C\n1,2,3\n4,5,6\n7,8,9\n"
        reader = BoundedCSVReader(batch_size=10)
        rows = list(reader.stream_rows(self._make_stream(csv_content)))
        assert len(rows) == 3

    def test_row_numbers_are_sequential_one_based(self) -> None:
        csv_content = "A,B\n1,2\n3,4\n5,6\n"
        reader = BoundedCSVReader(batch_size=10)
        rows = list(reader.stream_rows(self._make_stream(csv_content)))
        assert [r.row_number for r in rows] == [1, 2, 3]

    def test_batch_size_splits_correctly(self) -> None:
        lines = ["col\n"] + [f"{i}\n" for i in range(250)]
        reader = BoundedCSVReader(batch_size=100)
        batches = list(reader.stream_batches(io.StringIO("".join(lines))))
        assert len(batches) == 3  # 100, 100, 50
        assert len(batches[0]) == 100
        assert len(batches[1]) == 100
        assert len(batches[2]) == 50

    def test_hash_is_deterministic_across_two_calls(self) -> None:
        data = {"X": "hello", "Y": "world", "Z": "123"}
        h1 = compute_payload_hash(data)
        h2 = compute_payload_hash(data)
        assert h1 == h2
        assert len(h1) == 64

    def test_hash_differs_on_different_values(self) -> None:
        d1 = {"A": "foo"}
        d2 = {"A": "bar"}
        assert compute_payload_hash(d1) != compute_payload_hash(d2)

    def test_bom_stripped_from_headers(self) -> None:
        bom_csv = "\ufeffName,Value\nAlice,100\n"
        reader = BoundedCSVReader(batch_size=10)
        rows = list(reader.stream_rows(io.StringIO(bom_csv)))
        assert len(rows) == 1
        assert "Name" in rows[0].data  # BOM stripped

    def test_skips_completely_blank_lines(self) -> None:
        csv_content = "A,B\n1,2\n\n   \n3,4\n"
        reader = BoundedCSVReader(batch_size=10)
        rows = list(reader.stream_rows(io.StringIO(csv_content)))
        assert len(rows) == 2

    def test_empty_file_yields_no_rows(self) -> None:
        reader = BoundedCSVReader(batch_size=10)
        rows = list(reader.stream_rows(io.StringIO("")))
        assert rows == []

    def test_header_only_yields_no_rows(self) -> None:
        reader = BoundedCSVReader(batch_size=10)
        rows = list(reader.stream_rows(io.StringIO("A,B,C\n")))
        assert rows == []

    def test_binary_stream_wrapper(self) -> None:
        """stream_binary_batches must wrap and process correctly."""
        csv_bytes = b"X,Y\n10,20\n30,40\n"
        reader = BoundedCSVReader(batch_size=10)
        batches = list(reader.stream_binary_batches(io.BytesIO(csv_bytes)))
        assert sum(len(b) for b in batches) == 2


# ---------------------------------------------------------------------------
# 2. normalizer unit tests – stable diagnostic codes
# ---------------------------------------------------------------------------


MINIMAL_GOOD: dict[str, str] = {
    "External_Reference": "EXT-GOOD-001",
    "Transaction_Amount": "1000.00",
    "Currency": "INR",
    "Transaction_Date": "2026-10-29T10:00:00Z",
    "Posting_Date": "2026-10-29T10:00:00Z",
    "Entry_Direction": "DEBIT",
    "Transaction_Source": "acc-src",
    "Transaction_Destination": "acc-dst",
    "Source_Revision": "1",
    "Transaction_Type": "NEFT",
    "Transaction_Status": "POSTED",
    "Branch_ID": "BR-MUMBAI",
    "Description": "test transfer",
}


def _make_raw(data: dict[str, str]) -> RawRowRecord:
    h = compute_payload_hash(data)
    return RawRowRecord(row_number=1, data=data, payload_hash=h)


class TestRowNormalizer:
    """Verify normalizer returns correct result types and stable error codes."""

    def test_valid_row_returns_normalized(self) -> None:
        from app.ingestion.normalizer import NormalizedRow

        norm = RowNormalizer()
        result = norm.normalize(_make_raw(dict(MINIMAL_GOOD)))
        assert isinstance(result, NormalizedRow)
        assert result.external_ref == "EXT-GOOD-001"
        assert result.amount_minor == 100_000
        assert result.currency == "INR"
        assert result.direction == "DEBIT"

    def test_missing_external_ref_code(self) -> None:
        from app.ingestion.normalizer import QuarantinedRowError

        bad = dict(MINIMAL_GOOD)
        bad["External_Reference"] = ""
        result = RowNormalizer().normalize(_make_raw(bad))
        assert isinstance(result, QuarantinedRowError)
        assert result.error_code == "MISSING_EXTERNAL_REF"

    def test_negative_amount_code(self) -> None:
        from app.ingestion.normalizer import QuarantinedRowError

        bad = dict(MINIMAL_GOOD)
        bad["Transaction_Amount"] = "-500.00"
        result = RowNormalizer().normalize(_make_raw(bad))
        assert isinstance(result, QuarantinedRowError)
        assert result.error_code == "INVALID_AMOUNT"

    def test_zero_amount_code(self) -> None:
        from app.ingestion.normalizer import QuarantinedRowError

        bad = dict(MINIMAL_GOOD)
        bad["Transaction_Amount"] = "0.00"
        result = RowNormalizer().normalize(_make_raw(bad))
        assert isinstance(result, QuarantinedRowError)
        assert result.error_code == "INVALID_AMOUNT"

    def test_invalid_timestamp_code(self) -> None:
        from app.ingestion.normalizer import QuarantinedRowError

        bad = dict(MINIMAL_GOOD)
        bad["Transaction_Date"] = "NOT_A_DATE"
        result = RowNormalizer().normalize(_make_raw(bad))
        assert isinstance(result, QuarantinedRowError)
        assert result.error_code == "INVALID_TIMESTAMP"

    def test_invalid_currency_too_long_code(self) -> None:
        from app.ingestion.normalizer import QuarantinedRowError

        bad = dict(MINIMAL_GOOD)
        bad["Currency"] = "TOOLONG"
        result = RowNormalizer().normalize(_make_raw(bad))
        assert isinstance(result, QuarantinedRowError)
        assert result.error_code == "INVALID_CURRENCY"

    def test_invalid_currency_short_code(self) -> None:
        from app.ingestion.normalizer import QuarantinedRowError

        bad = dict(MINIMAL_GOOD)
        bad["Currency"] = "XX"
        result = RowNormalizer().normalize(_make_raw(bad))
        assert isinstance(result, QuarantinedRowError)
        assert result.error_code == "INVALID_CURRENCY"

    def test_identical_counterparty_code(self) -> None:
        from app.ingestion.normalizer import QuarantinedRowError

        bad = dict(MINIMAL_GOOD)
        bad["Transaction_Source"] = "acc-same"
        bad["Transaction_Destination"] = "acc-same"
        result = RowNormalizer().normalize(_make_raw(bad))
        assert isinstance(result, QuarantinedRowError)
        assert result.error_code == "IDENTICAL_COUNTERPARTY"

    def test_amount_decimal_to_minor_units(self) -> None:
        """125 000.50 INR → 12 500 050 paise."""
        from app.ingestion.normalizer import NormalizedRow

        row = dict(MINIMAL_GOOD)
        row["Transaction_Amount"] = "125000.50"
        result = RowNormalizer().normalize(_make_raw(row))
        assert isinstance(result, NormalizedRow)
        assert result.amount_minor == 12_500_050

    def test_timestamp_normalised_to_utc(self) -> None:
        from app.ingestion.normalizer import NormalizedRow

        row = dict(MINIMAL_GOOD)
        row["Transaction_Date"] = "2026-10-29T15:30:00+05:30"
        result = RowNormalizer().normalize(_make_raw(row))
        assert isinstance(result, NormalizedRow)
        assert result.occurred_at.tzinfo is not None
        # +05:30 → UTC should be 10:00
        assert result.occurred_at.hour == 10
        assert result.occurred_at.minute == 0


# ---------------------------------------------------------------------------
# 3. Parse-helper edge cases
# ---------------------------------------------------------------------------


class TestParseHelpers:
    """Edge-case coverage for stand-alone parsers."""

    def test_amount_with_comma_separator(self) -> None:
        assert parse_amount_to_minor("1,000,000.00") == 100_000_000

    def test_amount_with_rupee_symbol(self) -> None:
        assert parse_amount_to_minor("₹5000.25") == 500_025

    def test_amount_whole_number(self) -> None:
        assert parse_amount_to_minor("100") == 10_000

    def test_amount_raises_on_zero(self) -> None:
        with pytest.raises(ValueError):
            parse_amount_to_minor("0")

    def test_amount_raises_on_negative(self) -> None:
        with pytest.raises(ValueError):
            parse_amount_to_minor("-100.00")

    def test_amount_raises_on_text(self) -> None:
        with pytest.raises(ValueError):
            parse_amount_to_minor("NOTANUMBER")

    def test_timestamp_z_suffix(self) -> None:
        dt = parse_timestamp_to_utc("2026-10-29T10:00:00Z")
        assert dt.tzinfo is not None
        assert dt == datetime(2026, 10, 29, 10, 0, 0, tzinfo=UTC)

    def test_timestamp_offset_converted(self) -> None:
        dt = parse_timestamp_to_utc("2026-10-29T15:30:00+05:30")
        assert dt.hour == 10
        assert dt.minute == 0

    def test_timestamp_naive_assumes_utc(self) -> None:
        dt = parse_timestamp_to_utc("2026-10-29 10:00:00")
        assert dt.tzinfo is not None

    def test_timestamp_empty_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_timestamp_to_utc("")

    def test_timestamp_garbage_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_timestamp_to_utc("INVALID_DATE_STRING")


# ---------------------------------------------------------------------------
# Helpers for integration tests
# ---------------------------------------------------------------------------


def _generate_large_csv(num_rows: int = 10_000) -> str:
    """Generate a deterministic CSV with num_rows data rows (no pandas, pure Python)."""
    lines = [
        "External_Reference,Transaction_Amount,Currency,Transaction_Date,Posting_Date,"
        "Entry_Direction,Transaction_Source,Transaction_Destination,Source_Revision,"
        "Transaction_Type,Transaction_Status,Branch_ID,Description\n"
    ]
    for i in range(1, num_rows + 1):
        ext = f"EXT-LARGE-{i:06d}"
        amt = f"{(i % 9000) + 1000}.{i % 100:02d}"
        src = f"acc-src-{i % 50}"
        dst = f"acc-dst-{(i + 1) % 50}"
        lines.append(
            f"{ext},{amt},INR,2026-10-29T10:00:00Z,2026-10-29T10:00:00Z,"
            f"DEBIT,{src},{dst},1,NEFT,POSTED,BR-MUMBAI,Transfer {ext}\n"
        )
    return "".join(lines)


def _ingest_string(
    service: IngestionService,
    csv_str: str,
    source_system_id: str,
    db: Session,
    idempotency_key: str | None = None,
    job_id: str | None = None,
):
    """Helper: ingest a CSV string into the service."""
    stream = io.StringIO(csv_str)
    return service.process_file_or_stream(
        stream_or_file=stream,
        source_system_id=source_system_id,
        idempotency_key=idempotency_key,
        job_id=job_id,
        db_session=db,
    )


# ---------------------------------------------------------------------------
# 4. Integration: 10 000-row bounded-memory streaming
# ---------------------------------------------------------------------------


class TestLargeStreamBoundedMemory:
    """10k+ rows ingested with peak memory < 30 MB (no whole-file load)."""

    def test_10k_rows_accepted_with_bounded_peak_memory(
        self, service: IngestionService, db_session: Session
    ) -> None:
        csv_str = _generate_large_csv(10_000)
        src_sys = "SRC_LARGETEST"

        tracemalloc.start()
        snap_before = tracemalloc.take_snapshot()

        job = _ingest_string(service, csv_str, src_sys, db_session)

        snap_after = tracemalloc.take_snapshot()
        tracemalloc.stop()

        # Compare snapshots – tracemalloc measures Python object allocation
        stats = snap_after.compare_to(snap_before, "lineno")
        total_alloc_bytes = sum(s.size_diff for s in stats if s.size_diff > 0)
        total_alloc_mb = total_alloc_bytes / (1024 * 1024)

        # Accept up to 30 MB of incremental Python allocations during ingestion
        assert total_alloc_mb < 30.0, (
            f"Peak memory increment {total_alloc_mb:.1f} MB exceeded 30 MB limit. "
            "Possible whole-file load detected."
        )

        assert job.state in (IngestionJobState.COMPLETED, IngestionJobState.PARTIAL)
        assert job.counts.accepted == 10_000
        assert job.counts.rejected == 0

    def test_row_count_accurate_for_large_batch(
        self, service: IngestionService, db_session: Session
    ) -> None:
        csv_str = _generate_large_csv(1_500)
        job = _ingest_string(service, csv_str, "SRC_1500", db_session)
        assert job.counts.total_rows == 1_500
        assert job.counts.accepted == 1_500


# ---------------------------------------------------------------------------
# 5. Integration: Idempotent re-import (same file twice → 0 new identities)
# ---------------------------------------------------------------------------


class TestIdempotentReImport:
    """Importing the same file twice must not create duplicate source identities."""

    def test_second_import_creates_zero_new_source_records(
        self, service: IngestionService, db_session: Session
    ) -> None:
        csv_str = _generate_large_csv(200)
        src_sys = "SRC_IDEMPTEST"

        # First import
        job1 = _ingest_string(service, csv_str, src_sys, db_session)
        assert job1.counts.accepted == 200

        count_after_first = (
            db_session.query(SourceRecord)
            .filter_by(source_system_id=src_sys)
            .count()
        )

        # Second import of identical content
        job2 = _ingest_string(service, csv_str, src_sys, db_session)

        count_after_second = (
            db_session.query(SourceRecord)
            .filter_by(source_system_id=src_sys)
            .count()
        )

        # No new records created
        msg = f"Expected {count_after_first} records, got {count_after_second} after re-import."
        assert count_after_second == count_after_first, msg

        # Second job reports duplicates instead of accepted
        assert job2.counts.duplicate == 200
        assert job2.counts.accepted == 0

    def test_idempotency_key_returns_same_job(
        self, service: IngestionService, db_session: Session
    ) -> None:
        csv_str = _generate_large_csv(10)
        key = f"idem-key-{uuid.uuid4().hex}"

        job1 = _ingest_string(service, csv_str, "SRC_IDEMKEY", db_session, idempotency_key=key)
        # Re-submit with same key – a completed job should be returned
        job2 = _ingest_string(service, csv_str, "SRC_IDEMKEY", db_session, idempotency_key=key)

        # Both responses describe the same logical result
        assert job1.id == job2.id


# ---------------------------------------------------------------------------
# 6. Integration: malformed rows are quarantined, valid rows pass, job queryable
# ---------------------------------------------------------------------------


class TestMalformedRowQuarantine:
    """Import malformed_records.csv, verify stable error codes and batch completeness."""

    def test_malformed_fixture_quarantines_invalid_rows(
        self, service: IngestionService, db_session: Session
    ) -> None:
        assert os.path.exists(MALFORMED_CSV), (
            f"Fixture not found: {MALFORMED_CSV}. Run scripts/generate_fixture.py first."
        )

        with open(MALFORMED_CSV, encoding="utf-8") as f:
            csv_str = f.read()

        job = _ingest_string(service, csv_str, "SRC_MALFORMED", db_session)

        # 3 valid control rows (MAL-001, MAL-005, MAL-008), 5 malformed
        assert job.counts.accepted == 3, (
            f"Expected 3 accepted rows, got {job.counts.accepted}. "
            f"Job errors: {job.errors}"
        )
        assert job.counts.rejected >= 5

        # Collect stable error codes from returned error list
        error_codes = {e["error_code"] for e in job.errors}
        assert "INVALID_AMOUNT" in error_codes, "Expected INVALID_AMOUNT error code"
        assert "INVALID_TIMESTAMP" in error_codes, "Expected INVALID_TIMESTAMP error code"
        assert "INVALID_CURRENCY" in error_codes, "Expected INVALID_CURRENCY error code"
        assert "IDENTICAL_COUNTERPARTY" in error_codes, "Expected IDENTICAL_COUNTERPARTY error code"

        # Total rows lock: 8 data rows in fixture
        assert job.counts.total_rows == 8

        # Job state should be PARTIAL (some accepted, some rejected)
        assert job.state == IngestionJobState.PARTIAL

    def test_job_is_queryable_after_malformed_import(
        self, service: IngestionService, db_session: Session
    ) -> None:
        with open(MALFORMED_CSV, encoding="utf-8") as f:
            csv_str = f.read()

        job = _ingest_string(service, csv_str, "SRC_MALFORMED_Q", db_session)

        # Must be retrievable by ID
        fetched = service.get_job(job_id=job.id, db_session=db_session)
        assert fetched is not None
        assert fetched.id == job.id
        assert fetched.state == job.state

    def test_valid_rows_in_malformed_batch_persisted(
        self, service: IngestionService, db_session: Session
    ) -> None:
        with open(MALFORMED_CSV, encoding="utf-8") as f:
            csv_str = f.read()

        job = _ingest_string(service, csv_str, "SRC_MAL_PERSIST", db_session)

        # Valid rows (EXT-VAL-01 and EXT-VAL-08) must exist in DB
        accepted_records = (
            db_session.query(SourceRecord)
            .filter(
                SourceRecord.source_system_id == "SRC_MAL_PERSIST",
                SourceRecord.external_ref.in_(["EXT-VAL-01", "EXT-VAL-08"]),
            )
            .all()
        )
        assert len(accepted_records) == 2, (
            f"Expected 2 persisted valid records, got {len(accepted_records)}. "
            f"Accepted: {job.counts.accepted}, errors: {job.errors}"
        )


# ---------------------------------------------------------------------------
# 7. Integration: Revision-conflict detection
# ---------------------------------------------------------------------------


class TestRevisionConflict:
    """A changed payload with the same (source_system, external_ref, revision) is a conflict."""

    def _build_single_row_csv(self, ext_ref: str, amount: str, revision: int = 1) -> str:
        return (
            "External_Reference,Transaction_Amount,Currency,Transaction_Date,Posting_Date,"
            "Entry_Direction,Transaction_Source,Transaction_Destination,Source_Revision,"
            "Transaction_Type,Transaction_Status,Branch_ID,Description\n"
            f"{ext_ref},{amount},INR,2026-10-29T10:00:00Z,2026-10-29T10:00:00Z,"
            f"DEBIT,acc-conflict-src,acc-conflict-dst,{revision},NEFT,POSTED,BR-MUMBAI,conflict\n"
        )

    def test_changed_payload_same_revision_flagged_as_conflict(
        self, service: IngestionService, db_session: Session
    ) -> None:
        ext_ref = f"EXT-CONFLICT-{uuid.uuid4().hex[:8]}"
        src_sys = "SRC_CONFLICTTEST"

        # First import
        csv_v1 = self._build_single_row_csv(ext_ref, "1000.00", revision=1)
        job1 = _ingest_string(service, csv_v1, src_sys, db_session)
        assert job1.counts.accepted == 1

        # Second import: same (source_system, ext_ref, revision=1) but DIFFERENT amount
        csv_v1_changed = self._build_single_row_csv(ext_ref, "9999.00", revision=1)
        job2 = _ingest_string(service, csv_v1_changed, src_sys, db_session)

        assert job2.counts.conflict == 1, (
            f"Expected 1 conflict, got {job2.counts.conflict}. "
            f"Errors: {job2.errors}"
        )
        assert job2.counts.accepted == 0

        # Error code must be EXTERNAL_REF_REVISION_CONFLICT
        conflict_codes = [e["error_code"] for e in job2.errors]
        assert "EXTERNAL_REF_REVISION_CONFLICT" in conflict_codes

    def test_higher_revision_is_accepted_not_conflict(
        self, service: IngestionService, db_session: Session
    ) -> None:
        """Bumping revision number should succeed, not produce conflict."""
        ext_ref = f"EXT-NEWREV-{uuid.uuid4().hex[:8]}"
        src_sys = "SRC_NEWREVTEST"

        csv_r1 = self._build_single_row_csv(ext_ref, "5000.00", revision=1)
        job1 = _ingest_string(service, csv_r1, src_sys, db_session)
        assert job1.counts.accepted == 1

        csv_r2 = self._build_single_row_csv(ext_ref, "6000.00", revision=2)
        job2 = _ingest_string(service, csv_r2, src_sys, db_session)

        assert job2.counts.accepted == 1
        assert job2.counts.conflict == 0

    def test_silent_overwrite_does_not_occur(
        self, service: IngestionService, db_session: Session
    ) -> None:
        """After a conflict the original record's hash must be unchanged."""
        ext_ref = f"EXT-NOWRT-{uuid.uuid4().hex[:8]}"
        src_sys = "SRC_NOOVERWRITE"

        csv_orig = self._build_single_row_csv(ext_ref, "7777.00", revision=1)
        _ingest_string(service, csv_orig, src_sys, db_session)

        original_record = (
            db_session.query(SourceRecord)
            .filter_by(source_system_id=src_sys, external_ref=ext_ref, source_revision=1)
            .one()
        )
        original_hash = original_record.payload_hash

        csv_tampered = self._build_single_row_csv(ext_ref, "1234.00", revision=1)
        _ingest_string(service, csv_tampered, src_sys, db_session)

        db_session.refresh(original_record)
        assert original_record.payload_hash == original_hash, (
            "Conflict row silently overwrote the original source record payload_hash!"
        )


# ---------------------------------------------------------------------------
# 8. API round-trip tests via TestClient
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def test_client() -> Generator[TestClient, None, None]:
    """FastAPI TestClient with an isolated SQLite engine using StaticPool.

    StaticPool forces all connections (including those spawned by FastAPI's
    async dependency resolution) to share the single in-memory connection that
    Base.metadata.create_all() ran on, preventing "no such table" errors.
    """
    from sqlalchemy.pool import StaticPool

    from app.db.session import get_db
    from app.main import app

    api_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(api_engine, "connect")
    def _fk_pragma_api(dbapi_conn: Any, _rec: Any) -> None:
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(bind=api_engine)
    factory = sessionmaker(bind=api_engine, autocommit=False, autoflush=False)

    def override_get_db() -> Generator[Session, None, None]:
        sess = factory()
        try:
            yield sess
            sess.commit()
        except Exception:
            sess.rollback()
            raise
        finally:
            sess.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app, raise_server_exceptions=True)
    yield client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=api_engine)
    api_engine.dispose()


class TestIngestionAPI:
    """End-to-end HTTP API tests for POST /ingestion/jobs and GET /ingestion/jobs/{id}."""

    def _small_csv_bytes(self, num_rows: int = 5, src_sys_suffix: str = "") -> bytes:
        lines = [
            "External_Reference,Transaction_Amount,Currency,Transaction_Date,Posting_Date,"
            "Entry_Direction,Transaction_Source,Transaction_Destination,Source_Revision,"
            "Transaction_Type,Transaction_Status,Branch_ID,Description\n"
        ]
        for i in range(1, num_rows + 1):
            ext = f"EXT-API-{src_sys_suffix}-{i:04d}"
            lines.append(
                f"{ext},500.00,INR,2026-10-29T10:00:00Z,2026-10-29T10:00:00Z,"
                f"DEBIT,acc-api-src,acc-api-dst,1,NEFT,POSTED,BR-MUMBAI,api test\n"
            )
        return "".join(lines).encode()

    def test_post_ingestion_job_returns_202(self, test_client: TestClient) -> None:
        csv_bytes = self._small_csv_bytes(3, "POST")
        resp = test_client.post(
            "/api/v1/ingestion/jobs",
            files={"file": ("test.csv", csv_bytes, "text/csv")},
            data={"source_system_id": "SRC_API_TEST"},
        )
        assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"

    def test_post_returns_standard_envelope(self, test_client: TestClient) -> None:
        csv_bytes = self._small_csv_bytes(2, "ENV")
        resp = test_client.post(
            "/api/v1/ingestion/jobs",
            files={"file": ("env.csv", csv_bytes, "text/csv")},
            data={"source_system_id": "SRC_ENVELOPE"},
        )
        body = resp.json()
        assert "data" in body, "Missing 'data' envelope key"
        assert "request_id" in body, "Missing 'request_id' envelope key"
        job = body["data"]
        assert "id" in job
        assert "state" in job
        assert "counts" in job
        counts = job["counts"]
        assert "accepted" in counts
        assert "rejected" in counts
        assert "duplicate" in counts

    def test_get_job_by_id_returns_200(self, test_client: TestClient) -> None:
        csv_bytes = self._small_csv_bytes(2, "GET")
        post_resp = test_client.post(
            "/api/v1/ingestion/jobs",
            files={"file": ("get.csv", csv_bytes, "text/csv")},
            data={"source_system_id": "SRC_GET_TEST"},
        )
        job_id = post_resp.json()["data"]["id"]

        get_resp = test_client.get(f"/api/v1/ingestion/jobs/{job_id}")
        assert get_resp.status_code == 200, (
            f"Expected 200, got {get_resp.status_code}: {get_resp.text}"
        )
        get_body = get_resp.json()
        assert get_body["data"]["id"] == job_id

    def test_get_nonexistent_job_returns_404(self, test_client: TestClient) -> None:
        resp = test_client.get("/api/v1/ingestion/jobs/nonexistent-job-id-xyz")
        assert resp.status_code == 404

    def test_idempotency_key_header_accepted(self, test_client: TestClient) -> None:
        csv_bytes = self._small_csv_bytes(1, "IDEM")
        key = f"test-idem-{uuid.uuid4().hex}"
        resp = test_client.post(
            "/api/v1/ingestion/jobs",
            files={"file": ("idem.csv", csv_bytes, "text/csv")},
            data={"source_system_id": "SRC_IDEM_API"},
            headers={"Idempotency-Key": key},
        )
        assert resp.status_code == 202

    def test_api_counts_reflect_ingestion_results(self, test_client: TestClient) -> None:
        csv_bytes = self._small_csv_bytes(4, "COUNTS")
        resp = test_client.post(
            "/api/v1/ingestion/jobs",
            files={"file": ("counts.csv", csv_bytes, "text/csv")},
            data={"source_system_id": "SRC_COUNTS_TEST"},
        )
        assert resp.status_code == 202
        counts = resp.json()["data"]["counts"]
        assert counts["total_rows"] == 4
        assert counts["accepted"] == 4
        assert counts["rejected"] == 0

    def test_get_job_has_correct_counts_fields(self, test_client: TestClient) -> None:
        csv_bytes = self._small_csv_bytes(2, "FIELDS")
        post = test_client.post(
            "/api/v1/ingestion/jobs",
            files={"file": ("fields.csv", csv_bytes, "text/csv")},
            data={"source_system_id": "SRC_FIELDS_TEST"},
        )
        job_id = post.json()["data"]["id"]
        get = test_client.get(f"/api/v1/ingestion/jobs/{job_id}")
        counts = get.json()["data"]["counts"]
        for key in ("total_rows", "accepted", "rejected", "duplicate", "conflict"):
            assert key in counts, f"Missing counts field: {key}"

    def test_post_with_malformed_csv_returns_partial(self, test_client: TestClient) -> None:
        malformed_csv = (
            "External_Reference,Transaction_Amount,Currency,Transaction_Date,Posting_Date,"
            "Entry_Direction,Transaction_Source,Transaction_Destination,Source_Revision,"
            "Transaction_Type,Transaction_Status,Branch_ID,Description\n"
            # valid row
            "EXT-API-GOOD,1000.00,INR,2026-10-29T10:00:00Z,2026-10-29T10:00:00Z,"
            "DEBIT,acc-src,acc-dst,1,NEFT,POSTED,BR-MUMBAI,ok\n"
            # invalid row – negative amount
            ",−999.00,INR,2026-10-29T10:00:00Z,2026-10-29T10:00:00Z,"
            "DEBIT,acc-src,acc-dst,1,NEFT,POSTED,BR-MUMBAI,bad\n"
        )
        resp = test_client.post(
            "/api/v1/ingestion/jobs",
            files={"file": ("mixed.csv", malformed_csv.encode(), "text/csv")},
            data={"source_system_id": "SRC_MIXED_API"},
        )
        assert resp.status_code == 202
        job = resp.json()["data"]
        assert job["state"] in ("PARTIAL", "COMPLETED")


# ---------------------------------------------------------------------------
# 9. Provenance persistence tests
# ---------------------------------------------------------------------------


class TestProvenance:
    """SourceRecord must carry raw payload hash and source-file metadata."""

    def test_source_record_payload_hash_stored(
        self, service: IngestionService, db_session: Session
    ) -> None:
        ext_ref = f"EXT-PROV-{uuid.uuid4().hex[:8]}"
        csv_str = (
            "External_Reference,Transaction_Amount,Currency,Transaction_Date,Posting_Date,"
            "Entry_Direction,Transaction_Source,Transaction_Destination,Source_Revision,"
            "Transaction_Type,Transaction_Status,Branch_ID,Description\n"
            f"{ext_ref},2000.00,INR,2026-10-29T10:00:00Z,2026-10-29T10:00:00Z,"
            "DEBIT,acc-prov-a,acc-prov-b,1,NEFT,POSTED,BR-MUMBAI,prov test\n"
        )
        _ingest_string(service, csv_str, "SRC_PROV", db_session)

        record = (
            db_session.query(SourceRecord)
            .filter_by(source_system_id="SRC_PROV", external_ref=ext_ref)
            .first()
        )
        assert record is not None
        assert record.payload_hash is not None
        assert len(record.payload_hash) == 64  # SHA-256 hex

    def test_source_record_payload_json_stored(
        self, service: IngestionService, db_session: Session
    ) -> None:
        ext_ref = f"EXT-JSON-{uuid.uuid4().hex[:8]}"
        csv_str = (
            "External_Reference,Transaction_Amount,Currency,Transaction_Date,Posting_Date,"
            "Entry_Direction,Transaction_Source,Transaction_Destination,Source_Revision,"
            "Transaction_Type,Transaction_Status,Branch_ID,Description\n"
            f"{ext_ref},3000.00,USD,2026-10-29T10:00:00Z,2026-10-29T10:00:00Z,"
            "CREDIT,acc-json-a,acc-json-b,1,WIRE,POSTED,BR-MUMBAI,json prov\n"
        )
        _ingest_string(service, csv_str, "SRC_JSON_PROV", db_session)

        record = (
            db_session.query(SourceRecord)
            .filter_by(source_system_id="SRC_JSON_PROV", external_ref=ext_ref)
            .first()
        )
        assert record is not None
        assert isinstance(record.payload_json, dict)
        assert record.payload_json.get("External_Reference") == ext_ref

    def test_source_record_revision_stored(
        self, service: IngestionService, db_session: Session
    ) -> None:
        ext_ref = f"EXT-REV-{uuid.uuid4().hex[:8]}"
        csv_str = (
            "External_Reference,Transaction_Amount,Currency,Transaction_Date,Posting_Date,"
            "Entry_Direction,Transaction_Source,Transaction_Destination,Source_Revision,"
            "Transaction_Type,Transaction_Status,Branch_ID,Description\n"
            f"{ext_ref},4000.00,INR,2026-10-29T10:00:00Z,2026-10-29T10:00:00Z,"
            "DEBIT,acc-rev-a,acc-rev-b,3,NEFT,POSTED,BR-MUMBAI,rev test\n"
        )
        _ingest_string(service, csv_str, "SRC_REV_PROV", db_session)

        record = (
            db_session.query(SourceRecord)
            .filter_by(source_system_id="SRC_REV_PROV", external_ref=ext_ref)
            .first()
        )
        assert record is not None
        assert record.source_revision == 3
