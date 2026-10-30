from __future__ import annotations

import os
import sys
import uuid
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.db.models import (  # noqa: E402
    Base,
    Finding,
    Journal,
    JournalLine,
    SourceRecord,
    SourceRecordTransaction,
    Transaction,
    Account,
)
from app.ingestion.canonicalizer import Canonicalizer  # noqa: E402
from app.ingestion.normalizer import NormalizedRow  # noqa: E402
from app.schemas.detectors import FindingType  # noqa: E402

# ---------------------------------------------------------------------------
# In-Memory SQLite Fixtures (StaticPool ensures connection sharing)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def sqlite_engine():
    """Isolated in-memory SQLite engine with foreign key enforcement."""
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
def canonicalizer() -> Canonicalizer:
    return Canonicalizer(default_branch_id="br-canon-01")


def _make_row(
    ext_ref: str,
    amount_minor: int = 100000,
    sender: str = "acc-alice",
    receiver: str = "acc-bob",
    currency: str = "INR",
    revision: int = 1,
    row_num: int = 1,
    branch_id: str = "br-canon-01",
    occurred_at: datetime | None = None,
) -> NormalizedRow:
    now = occurred_at or datetime.now(UTC)
    return NormalizedRow(
        row_number=row_num,
        external_ref=ext_ref,
        source_revision=revision,
        sender_account_id=sender,
        receiver_account_id=receiver,
        amount_minor=amount_minor,
        currency=currency,
        occurred_at=now,
        posted_at=now,
        direction="DEBIT",
        txn_type="TRANSFER",
        status="POSTED",
        branch_id=branch_id,
        description=f"Transfer {ext_ref}",
        raw_payload={"ext": ext_ref, "amount": amount_minor},
        payload_hash=f"hash-{ext_ref}-{amount_minor}-{revision}",
    )


# ---------------------------------------------------------------------------
# 1. Canonicalizer Duplicate Collapsing & Provenance
# ---------------------------------------------------------------------------


class TestCanonicalizerCollapsing:
    """Verify accepted duplicate references collapse to one canonical event."""

    def test_repeated_transport_copies_collapse_to_one_canonical_event(
        self, canonicalizer: Canonicalizer, db_session: Session
    ) -> None:
        ext_ref = f"EXT-COLLAPSE-{uuid.uuid4().hex[:8]}"
        job_1 = "job-stream-001"
        job_2 = "job-stream-002"

        row_1 = _make_row(ext_ref=ext_ref, amount_minor=250000, row_num=1)
        res_1 = canonicalizer.canonicalize_row(db_session, row_1, job_1, "CORE_BANKING")
        assert res_1.is_new is True
        assert res_1.is_duplicate is False
        db_session.add_all([res_1.source_record, res_1.transaction, res_1.junction])
        db_session.commit()

        # Second transport copy: identical financial facts, separate job/source record
        row_2 = _make_row(ext_ref=ext_ref, amount_minor=250000, row_num=2, revision=2)
        res_2 = canonicalizer.canonicalize_row(db_session, row_2, job_2, "CORE_BANKING")
        assert res_2.is_new is False
        assert res_2.is_duplicate is True
        assert res_2.transaction.id == res_1.transaction.id
        db_session.add_all([res_2.source_record, res_2.junction])
        db_session.commit()

        # Verify DB state: 2 source records, 1 canonical transaction
        src_records = (
            db_session.query(SourceRecord)
            .filter_by(external_ref=ext_ref)
            .all()
        )
        assert len(src_records) == 2

        txns = (
            db_session.query(Transaction)
            .filter_by(external_canonical_ref=f"CANON-CORE_BANKING-{ext_ref}")
            .all()
        )
        assert len(txns) == 1
        assert txns[0].amount_minor == 250000

        # Verify lineage links
        links = (
            db_session.query(SourceRecordTransaction)
            .filter_by(transaction_id=txns[0].id)
            .all()
        )
        assert len(links) == 2
        link_types = {link.link_type for link in links}
        assert "CANONICAL" in link_types
        assert "DUPLICATE_COLLAPSED" in link_types


# ---------------------------------------------------------------------------
# 2. Ambiguous Duplicates Handling
# ---------------------------------------------------------------------------


class TestAmbiguousDuplicates:
    """Verify conflicting duplicate facts are quarantined for review without overwrite."""

    def test_conflicting_duplicate_retained_for_review(
        self, canonicalizer: Canonicalizer, db_session: Session
    ) -> None:
        ext_ref = f"EXT-AMB-{uuid.uuid4().hex[:8]}"

        # Original transaction: 100,000 paise
        row_1 = _make_row(ext_ref=ext_ref, amount_minor=100000)
        res_1 = canonicalizer.canonicalize_row(db_session, row_1, "job-1", "CLEARING")
        db_session.add_all([res_1.source_record, res_1.transaction, res_1.junction])
        db_session.commit()

        # Conflicting duplicate: same external_ref but differing amount (180,000 paise)
        row_2 = _make_row(ext_ref=ext_ref, amount_minor=180000, revision=2)
        res_2 = canonicalizer.canonicalize_row(db_session, row_2, "job-2", "CLEARING")

        assert res_2.is_ambiguous is True
        assert res_2.is_duplicate is False
        assert res_2.source_record.record_status == "AMBIGUOUS"
        assert res_2.junction.link_type == "AMBIGUOUS_DUPLICATE"

        db_session.add_all([res_2.source_record, res_2.junction])
        db_session.commit()

        # Canonical transaction amount remains unchanged
        txn = db_session.query(Transaction).filter_by(id=res_1.transaction.id).one()
        assert txn.amount_minor == 100000


# ---------------------------------------------------------------------------
# 3. Reversible Corrections
# ---------------------------------------------------------------------------


class TestReversibleCorrections:
    """Verify corrections are reversible with full provenance history."""

    def test_corrections_and_reversals_are_reversible(
        self, canonicalizer: Canonicalizer, db_session: Session
    ) -> None:
        ext_ref = f"EXT-REV-{uuid.uuid4().hex[:8]}"
        row = _make_row(ext_ref=ext_ref, amount_minor=300000)
        res = canonicalizer.canonicalize_row(db_session, row, "job-rev", "SWIFT")
        db_session.add_all([res.source_record, res.transaction, res.junction])
        db_session.commit()

        txn_id = res.transaction.id
        assert res.transaction.status == "POSTED"

        # Apply reversal/correction
        correction_src = SourceRecord(
            id=f"src-{uuid.uuid4().hex[:16]}",
            ingestion_job_id="job-rev",
            source_system_id="SWIFT",
            external_ref=ext_ref,
            source_revision=2,
            payload_json={"action": "REVERSAL", "reason": "Customer cancellation"},
            payload_hash="hash-rev-01",
            received_at=datetime.now(UTC),
            record_status="ACCEPTED",
        )
        db_session.add(correction_src)
        db_session.flush()

        txn, corr_link = canonicalizer.apply_correction(
            db_session,
            transaction_id=txn_id,
            correction_source_record=correction_src,
            new_status="REVERSED",
            link_type="REVERSAL",
        )
        db_session.commit()
        assert txn.status == "REVERSED"
        assert corr_link.link_type == "REVERSAL"

        # Revert the correction: restore status to POSTED
        revert_src = SourceRecord(
            id=f"src-{uuid.uuid4().hex[:16]}",
            ingestion_job_id="job-rev",
            source_system_id="SWIFT",
            external_ref=ext_ref,
            source_revision=3,
            payload_json={"action": "UNREVERSE", "reason": "Audit review clear"},
            payload_hash="hash-rev-02",
            received_at=datetime.now(UTC),
            record_status="ACCEPTED",
        )
        db_session.add(revert_src)
        db_session.flush()

        txn_restored, rev_link = canonicalizer.revert_correction(
            db_session,
            transaction_id=txn_id,
            revert_source_record=revert_src,
            restored_status="POSTED",
        )
        db_session.commit()

        assert txn_restored.status == "POSTED"
        assert rev_link is not None
        assert rev_link.link_type == "CORRECTION_REVERTED"

        # All 3 lineage links exist and remain intact
        all_links = (
            db_session.query(SourceRecordTransaction)
            .filter_by(transaction_id=txn_id)
            .all()
        )
        assert len(all_links) == 3


# ---------------------------------------------------------------------------
# 4. Double-Entry Journal Integrity
# ---------------------------------------------------------------------------


class TestDoubleEntryJournalIntegrity:
    """Verify double-entry balance validation and unbalanced group flagging."""

    def test_balanced_journal_passes_and_marks_posted(
        self, canonicalizer: Canonicalizer, db_session: Session
    ) -> None:
        jrn_ref = f"JRN-BAL-{uuid.uuid4().hex[:8]}"
        lines = [
            ("acc-debit-1", 50000, 0),
            ("acc-credit-1", 0, 50000),
        ]
        journal, is_balanced, finding = canonicalizer.store_journal_lines(
            db_session=db_session,
            branch_id="br-canon-01",
            journal_ref=jrn_ref,
            lines_data=lines,
        )
        db_session.commit()

        assert is_balanced is True
        assert journal.status == "POSTED"
        assert finding is None

        # Verify lines in DB
        db_lines = db_session.query(JournalLine).filter_by(journal_id=journal.id).all()
        assert len(db_lines) == 2
        assert sum(line.debit_minor for line in db_lines) == 50000
        assert sum(line.credit_minor for line in db_lines) == 50000

    def test_unbalanced_journal_flagged_with_original_postings_traceable(
        self, canonicalizer: Canonicalizer, db_session: Session
    ) -> None:
        jrn_ref = f"JRN-UNBAL-{uuid.uuid4().hex[:8]}"
        # Debit 100,000 paise vs Credit 95,000 paise -> 5,000 paise imbalance
        lines = [
            ("acc-unbal-d", 100000, 0),
            ("acc-unbal-c", 0, 95000),
        ]
        journal, is_balanced, finding = canonicalizer.store_journal_lines(
            db_session=db_session,
            branch_id="br-canon-01",
            journal_ref=jrn_ref,
            lines_data=lines,
        )
        db_session.commit()

        assert is_balanced is False
        assert journal.status == "UNBALANCED"
        assert finding is not None
        assert finding.finding_type == FindingType.UNBALANCED_JOURNAL.value
        assert finding.evidence_json["facts"]["Balance_Anomaly_Flag"] is True
        assert finding.evidence_json["facts"]["Reconciliation_Variance_Minor"] == 5000
        assert finding.evidence_json["imbalance_minor"] == 5000

        # Verify original postings remain traceable in DB (never deleted)
        persisted_lines = (
            db_session.query(JournalLine)
            .filter_by(journal_id=journal.id)
            .all()
        )
        assert len(persisted_lines) == 2
        debits = sum(line.debit_minor for line in persisted_lines)
        credits = sum(line.credit_minor for line in persisted_lines)
        assert debits == 100000
        assert credits == 95000

        # Finding is queryable in DB
        persisted_finding = db_session.query(Finding).filter_by(id=finding.id).one()
        assert persisted_finding.evidence_json["journal_id"] == journal.id


# ---------------------------------------------------------------------------
# 5. Downstream Snapshot Uniqueness Guarantee
# ---------------------------------------------------------------------------


class TestDownstreamSnapshot:
    """Guarantee replays and retries never add extra transfers to downstream detectors."""

    def test_snapshot_contains_only_unique_canonical_transfers(
        self, canonicalizer: Canonicalizer, db_session: Session
    ) -> None:
        ext_1 = f"EXT-SNAP-1-{uuid.uuid4().hex[:8]}"
        ext_2 = f"EXT-SNAP-2-{uuid.uuid4().hex[:8]}"
        ext_3 = f"EXT-SNAP-3-{uuid.uuid4().hex[:8]}"

        t0 = datetime(2026, 10, 29, 10, 0, 0, tzinfo=UTC)

        # Ingest 3 distinct transfers
        row_1 = _make_row(ext_ref=ext_1, amount_minor=10000, occurred_at=t0)
        row_2 = _make_row(ext_ref=ext_2, amount_minor=20000, occurred_at=t0 + timedelta(minutes=5))
        row_3 = _make_row(ext_ref=ext_3, amount_minor=30000, occurred_at=t0 + timedelta(minutes=10))

        res_1 = canonicalizer.canonicalize_row(db_session, row_1, "job-1", "SRC_A")
        res_2 = canonicalizer.canonicalize_row(db_session, row_2, "job-1", "SRC_A")
        res_3 = canonicalizer.canonicalize_row(db_session, row_3, "job-1", "SRC_A")

        db_session.add_all([res_1.source_record, res_1.transaction, res_1.junction])
        db_session.add_all([res_2.source_record, res_2.transaction, res_2.junction])
        db_session.add_all([res_3.source_record, res_3.transaction, res_3.junction])
        db_session.commit()

        # Replay / transport retry of row_1 and row_2 (multiple times)
        row_1_r2 = _make_row(ext_ref=ext_1, amount_minor=10000, occurred_at=t0, revision=2)
        row_1_r3 = _make_row(ext_ref=ext_1, amount_minor=10000, occurred_at=t0, revision=3)
        row_2_r2 = _make_row(
            ext_ref=ext_2, amount_minor=20000, occurred_at=t0 + timedelta(minutes=5), revision=2
        )

        res_1_dup1 = canonicalizer.canonicalize_row(db_session, row_1_r2, "job-replay-1", "SRC_A")
        res_1_dup2 = canonicalizer.canonicalize_row(db_session, row_1_r3, "job-replay-2", "SRC_A")
        res_2_dup1 = canonicalizer.canonicalize_row(db_session, row_2_r2, "job-replay-1", "SRC_A")

        db_session.add_all([res_1_dup1.source_record, res_1_dup1.junction])
        db_session.add_all([res_1_dup2.source_record, res_1_dup2.junction])
        db_session.add_all([res_2_dup1.source_record, res_2_dup1.junction])
        db_session.commit()

        # Database now holds 6 source records across multiple replay attempts
        total_sources = db_session.query(SourceRecord).count()
        assert total_sources == 6

        # Expose downstream snapshot
        snapshot = canonicalizer.get_downstream_snapshot(db_session)

        # Invariant: exactly 3 unique canonical transfers!
        assert len(snapshot) == 3
        txn_ids = [e.transaction_id for e in snapshot]
        assert len(set(txn_ids)) == 3

        # Amounts match original transfers
        amounts = [e.amount_minor for e in snapshot]
        assert amounts == [10000, 20000, 30000]

        # Verify time-window filtering
        filtered_snapshot = canonicalizer.get_downstream_snapshot(
            db_session,
            start_at=t0 + timedelta(minutes=4),
            end_at=t0 + timedelta(minutes=15),
        )
        assert len(filtered_snapshot) == 2
        assert [e.amount_minor for e in filtered_snapshot] == [20000, 30000]


# ---------------------------------------------------------------------------
# 6. API: GET /transactions (Cursor Pagination, Filters, Accounting Errors)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def test_client() -> Generator[TestClient, None, None]:
    """TestClient configured with isolated in-memory SQLite and shared connection."""
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
    session_factory = sessionmaker(bind=api_engine, autocommit=False, autoflush=False)
    app.state.session_factory = session_factory

    def _override_get_db() -> Generator[Session, None, None]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=api_engine)
    api_engine.dispose()


class TestTransactionsAPI:
    """Verify GET /transactions cursor pagination, filtering, and error flags."""

    def _seed_transactions(self, client: TestClient, count: int = 5) -> list[str]:
        canon = Canonicalizer()
        base_time = datetime(2026, 10, 29, 12, 0, 0, tzinfo=UTC)
        txn_ids = []

        with client.app.state.session_factory() as db:
            for i in range(count):
                ref = f"API-TXN-{i:03d}-{uuid.uuid4().hex[:6]}"
                row = _make_row(
                    ext_ref=ref,
                    amount_minor=(i + 1) * 10000,
                    sender=f"acc-src-{i % 2}",
                    receiver="acc-dst-fixed",
                    occurred_at=base_time + timedelta(minutes=i * 10),
                )
                res = canon.canonicalize_row(db, row, f"job-{i}", "API_SRC")
                db.add_all([res.source_record, res.transaction, res.junction])
                txn_ids.append(res.transaction.id)
            db.commit()

        return txn_ids

    def test_cursor_pagination_pages_sequentially(self, test_client: TestClient) -> None:
        self._seed_transactions(test_client, count=5)

        # Page 1: limit=2
        resp1 = test_client.get("/api/v1/transactions?limit=2")
        assert resp1.status_code == 200
        body1 = resp1.json()
        assert len(body1["data"]) == 2
        assert body1["meta"]["has_more"] is True
        assert body1["meta"]["total_count"] == 5
        cursor_1 = body1["meta"]["next_cursor"]
        assert cursor_1 is not None

        # Page 2: limit=2 with cursor
        resp2 = test_client.get(f"/api/v1/transactions?limit=2&cursor={cursor_1}")
        assert resp2.status_code == 200
        body2 = resp2.json()
        assert len(body2["data"]) == 2
        assert body2["meta"]["has_more"] is True
        cursor_2 = body2["meta"]["next_cursor"]
        assert cursor_2 is not None

        # Page 3: limit=2 with cursor
        resp3 = test_client.get(f"/api/v1/transactions?limit=2&cursor={cursor_2}")
        assert resp3.status_code == 200
        body3 = resp3.json()
        assert len(body3["data"]) == 1
        assert body3["meta"]["has_more"] is False
        assert body3["meta"]["next_cursor"] is None

        # Verify no overlapping IDs across pages
        ids_p1 = {item["id"] for item in body1["data"]}
        ids_p2 = {item["id"] for item in body2["data"]}
        ids_p3 = {item["id"] for item in body3["data"]}
        assert len(ids_p1 & ids_p2) == 0
        assert len(ids_p2 & ids_p3) == 0
        assert len(ids_p1 | ids_p2 | ids_p3) == 5

    def test_search_and_account_filtering(self, test_client: TestClient) -> None:
        self._seed_transactions(test_client, count=4)

        # Filter by sender account
        resp = test_client.get("/api/v1/transactions?sender_account_id=acc-src-0")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 2
        for item in data:
            assert item["sender_account_id"] == "acc-src-0"

        # Filter by minimum amount
        resp_min = test_client.get("/api/v1/transactions?min_amount_minor=30000")
        assert resp_min.status_code == 200
        min_data = resp_min.json()["data"]
        assert len(min_data) == 2
        for item in min_data:
            assert item["amount_minor"] >= 30000

    def test_accounting_integrity_error_filtering(self, test_client: TestClient) -> None:
        canon = Canonicalizer()

        with test_client.app.state.session_factory() as db:
            # Transaction 1: balanced journal
            ref_bal = f"TX-BAL-{uuid.uuid4().hex[:6]}"
            row_bal = _make_row(ext_ref=ref_bal, amount_minor=10000)
            res_bal = canon.canonicalize_row(db, row_bal, "job-bal", "BANK")
            db.add_all([res_bal.source_record, res_bal.transaction, res_bal.junction])

            # Transaction 2: unbalanced journal
            ref_unbal = f"TX-UNBAL-{uuid.uuid4().hex[:6]}"
            row_unbal = _make_row(ext_ref=ref_unbal, amount_minor=50000)
            res_unbal = canon.canonicalize_row(db, row_unbal, "job-unbal", "BANK")
            db.add_all([res_unbal.source_record, res_unbal.transaction, res_unbal.junction])

            # Force journal for Transaction 2 to be unbalanced
            jrn_ref = f"JRN-BANK-{ref_unbal}"
            journal = db.query(Journal).filter_by(journal_ref=jrn_ref).one()
            journal.status = "UNBALANCED"
            # Imbalance line
            unbal_line = JournalLine(
                id=f"jnl-err-{uuid.uuid4().hex[:8]}",
                journal_id=journal.id,
                account_id=row_unbal.sender_account_id,
                debit_minor=15000,
                credit_minor=0,
            )
            db.add(unbal_line)
            db.commit()

            bal_txn_id = res_bal.transaction.id
            unbal_txn_id = res_unbal.transaction.id

        # Query only transactions with accounting integrity error
        resp = test_client.get("/api/v1/transactions?has_accounting_error=true")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 1
        assert data[0]["id"] == unbal_txn_id
        err = data[0]["accounting_integrity_error"]
        assert err is not None
        assert err["error_code"] == "UNBALANCED_JOURNAL"
        assert err["imbalance_minor"] == 15000

        # Query transactions without accounting errors
        resp_clean = test_client.get("/api/v1/transactions?has_accounting_error=false")
        assert resp_clean.status_code == 200
        clean_data = resp_clean.json()["data"]
        assert any(item["id"] == bal_txn_id for item in clean_data)
        assert all(item["id"] != unbal_txn_id for item in clean_data)

    def test_downstream_snapshot_api_endpoint(self, test_client: TestClient) -> None:
        self._seed_transactions(test_client, count=3)

        resp = test_client.get("/api/v1/transactions/snapshot")
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert len(body["data"]) == 3
        first_event = body["data"][0]
        assert "transaction_id" in first_event
        assert "amount_minor" in first_event
        assert "currency" in first_event

    def test_get_single_transaction_by_id(self, test_client: TestClient) -> None:
        txn_ids = self._seed_transactions(test_client, count=1)
        target_id = txn_ids[0]

        resp = test_client.get(f"/api/v1/transactions/{target_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["id"] == target_id
        assert body["data"]["source_record_count"] >= 1

        # Nonexistent ID returns 404
        resp_404 = test_client.get("/api/v1/transactions/txn-does-not-exist")
        assert resp_404.status_code == 404

    def test_duplicate_resolution_on_concurrent_insert(self, canonicalizer: Canonicalizer, db_session: Session) -> None:
        ext_ref = f"EXT-CONCURRENT-{uuid.uuid4().hex[:8]}"
        row_1 = _make_row(ext_ref=ext_ref, amount_minor=250000, revision=1)
        row_2 = _make_row(ext_ref=ext_ref, amount_minor=250000, revision=2)

        res_1 = canonicalizer.canonicalize_row(db_session, row_1, "job-conc-1", "CORE_BANKING")
        db_session.add_all([res_1.source_record, res_1.transaction, res_1.junction])
        db_session.commit()

        res_2 = canonicalizer.canonicalize_row(db_session, row_2, "job-conc-2", "CORE_BANKING")
        assert res_2.is_duplicate is True
        db_session.add_all([res_2.source_record, res_2.junction])
        db_session.commit()

        txn_count = db_session.query(Transaction).filter_by(external_canonical_ref=f"CANON-CORE_BANKING-{ext_ref}").count()
        assert txn_count == 1

    def test_snapshot_uses_bounded_keyset_batches(self, canonicalizer: Canonicalizer, db_session: Session) -> None:
        base = datetime(2026, 10, 29, 10, 0, tzinfo=UTC)
        for i in range(12):
            row = _make_row(ext_ref=f"EXT-BATCH-{i:02d}-{uuid.uuid4().hex[:4]}", amount_minor=(i + 1) * 1000, occurred_at=base + timedelta(minutes=i))
            res = canonicalizer.canonicalize_row(db_session, row, f"job-batch-{i}", "BATCH_SRC")
            db_session.add_all([res.source_record, res.transaction, res.junction])
        db_session.commit()

        snapshot = list(canonicalizer.get_downstream_snapshot(db_session, batch_size=5))
        assert len(snapshot) == 12
        assert [event.amount_minor for event in snapshot] == sorted(event.amount_minor for event in snapshot)

    def test_auto_created_accounts_inherit_row_currency(self, canonicalizer: Canonicalizer, db_session: Session) -> None:
        row = _make_row(ext_ref=f"EXT-CURRENCY-{uuid.uuid4().hex[:8]}", amount_minor=12345, currency="USD")
        res = canonicalizer.canonicalize_row(db_session, row, "job-currency", "BANK_USD")
        assert res.transaction is not None
        assert res.junction is not None
        db_session.add_all([res.source_record, res.transaction, res.junction])
        db_session.commit()

        sender = db_session.query(Account).filter_by(id=row.sender_account_id).one()
        receiver = db_session.query(Account).filter_by(id=row.receiver_account_id).one()
        assert sender.currency == "USD"
        assert receiver.currency == "USD"

    def test_changed_timestamp_makes_duplicate_ambiguous(self, canonicalizer: Canonicalizer, db_session: Session) -> None:
        ext_ref = f"EXT-TSTAMP-{uuid.uuid4().hex[:8]}"
        row_1 = _make_row(ext_ref=ext_ref, amount_minor=50000, occurred_at=datetime(2026, 10, 29, 9, 0, tzinfo=UTC))
        row_2 = _make_row(ext_ref=ext_ref, amount_minor=50000, revision=2, occurred_at=datetime(2026, 10, 29, 9, 5, tzinfo=UTC))

        res_1 = canonicalizer.canonicalize_row(db_session, row_1, "job-tstamp-1", "TSTAMP_SRC")
        assert res_1.transaction is not None
        assert res_1.junction is not None
        db_session.add_all([res_1.source_record, res_1.transaction, res_1.junction])
        db_session.commit()

        res_2 = canonicalizer.canonicalize_row(db_session, row_2, "job-tstamp-2", "TSTAMP_SRC")
        assert res_2.transaction is not None
        assert res_2.junction is not None
        assert res_2.is_ambiguous is True
        assert res_2.is_duplicate is False
        assert res_2.source_record.record_status == "AMBIGUOUS"
        assert res_2.junction.link_type == "AMBIGUOUS_DUPLICATE"
