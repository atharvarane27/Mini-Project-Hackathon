import os
from datetime import UTC, datetime, timedelta

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.db.models import (
    Account,
    AuditCase,
    Base,
    Branch,
    IngestionJob,
    Journal,
    JournalLine,
    OutboxEvent,
    ReconciliationRun,
    SourceRecord,
    SourceSystem,
    Transaction,
    WorkflowEdge,
    WorkflowTaskTemplate,
    WorkflowTemplate,
)
from app.db.seed import seed_database


@pytest.fixture
def sqlite_engine():
    """Create an isolated in-memory SQLite engine with foreign key enforcement enabled."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def db_session(sqlite_engine):
    """Provide a transaction-bound session for schema testing."""
    session_factory = sessionmaker(bind=sqlite_engine, autocommit=False, autoflush=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


class TestAlembicMigrationLifecycle:
    """Test Alembic migrations up/down and repeatability on a file-based SQLite database."""

    def test_migration_upgrade_and_downgrade_repeatability(self, tmp_path):
        db_path = tmp_path / "test_migration.db"
        sqlite_url = f"sqlite:///{db_path}"

        alembic_ini_path = os.path.join(os.path.dirname(__file__), "..", "..", "alembic.ini")
        alembic_cfg = Config(alembic_ini_path)
        alembic_cfg.set_main_option("sqlalchemy.url", sqlite_url)

        # 1. Upgrade to head
        command.upgrade(alembic_cfg, "head")

        # 2. Downgrade to base
        command.downgrade(alembic_cfg, "base")

        # 3. Upgrade to head again (repeatability)
        command.upgrade(alembic_cfg, "head")


class TestCheckConstraints:
    """Verify that domain CHECK constraints are enforced by the database."""

    def test_reject_transaction_non_positive_amount(self, db_session):
        branch = Branch(id="br-01", code="BR01", name="Branch 1")
        acc1 = Account(id="acc-01", branch_id="br-01", currency="INR", masked_label="A1")
        acc2 = Account(id="acc-02", branch_id="br-01", currency="INR", masked_label="A2")
        db_session.add_all([branch, acc1, acc2])
        db_session.flush()

        now = datetime.now(UTC)
        invalid_txn = Transaction(
            id="txn-invalid",
            sender_account_id="acc-01",
            receiver_account_id="acc-02",
            amount_minor=0,  # Zero amount violates CHECK(amount_minor > 0)
            currency="INR",
            occurred_at=now,
            posted_at=now,
            txn_type="NEFT",
            status="POSTED",
        )
        db_session.add(invalid_txn)
        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_reject_journal_line_both_sides_positive(self, db_session):
        branch = Branch(id="br-01", code="BR01", name="Branch 1")
        acc = Account(id="acc-01", branch_id="br-01", currency="INR", masked_label="A1")
        journal = Journal(
            id="j-01",
            branch_id="br-01",
            posted_at=datetime.now(UTC),
            journal_ref="JREF-01",
        )
        db_session.add_all([branch, acc, journal])
        db_session.flush()

        # Both sides positive violates double-entry line validity
        invalid_line = JournalLine(
            id="jl-01",
            journal_id="j-01",
            account_id="acc-01",
            debit_minor=5000,
            credit_minor=5000,
        )
        db_session.add(invalid_line)
        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_reject_audit_case_priority_out_of_bounds(self, db_session):
        invalid_case = AuditCase(
            id="case-inv",
            case_code="CASE-INV",
            state="QUEUED",
            priority=150,  # Out of [0, 100] bounds
            row_version=1,
            created_at=datetime.now(UTC),
        )
        db_session.add(invalid_case)
        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_reject_reconciliation_cutoff_before_start(self, db_session):
        src1 = SourceSystem(id="S1", name="Source 1")
        src2 = SourceSystem(id="S2", name="Source 2")
        db_session.add_all([src1, src2])
        db_session.flush()

        now = datetime.now(UTC)
        invalid_run = ReconciliationRun(
            id="recon-inv",
            source_left_id="S1",
            source_right_id="S2",
            start_at=now,
            cutoff_at=now - timedelta(hours=1),  # Cutoff before start
            input_checkpoint="chk-01",
            status="PENDING",
        )
        db_session.add(invalid_run)
        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_reject_workflow_edge_self_loop(self, db_session):
        wf = WorkflowTemplate(id="wf-01", name="WF", version=1, status="DRAFT")
        task = WorkflowTaskTemplate(
            id="task-01",
            template_id="wf-01",
            stable_key="K1",
            display_name="T1",
        )
        db_session.add_all([wf, task])
        db_session.flush()

        # Self-edge violates CHECK(predecessor != successor)
        self_edge = WorkflowEdge(
            template_id="wf-01",
            predecessor_template_task_id="task-01",
            successor_template_task_id="task-01",
        )
        db_session.add(self_edge)
        with pytest.raises(IntegrityError):
            db_session.flush()


class TestForeignKeyRestrictConstraints:
    """Verify RESTRICT ondelete behavior protecting financial audit trails."""

    def test_branch_delete_blocked_when_accounts_exist(self, db_session):
        branch = Branch(id="br-01", code="BR01", name="Branch 1")
        acc = Account(id="acc-01", branch_id="br-01", currency="INR", masked_label="A1")
        db_session.add_all([branch, acc])
        db_session.flush()

        # Deleting branch must fail because account references it (ON DELETE RESTRICT)
        db_session.delete(branch)
        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_account_delete_blocked_when_transactions_exist(self, db_session):
        branch = Branch(id="br-01", code="BR01", name="Branch 1")
        acc1 = Account(id="acc-01", branch_id="br-01", currency="INR", masked_label="A1")
        acc2 = Account(id="acc-02", branch_id="br-01", currency="INR", masked_label="A2")
        db_session.add_all([branch, acc1, acc2])
        db_session.flush()

        now = datetime.now(UTC)
        txn = Transaction(
            id="txn-01",
            sender_account_id="acc-01",
            receiver_account_id="acc-02",
            amount_minor=100000,
            currency="INR",
            occurred_at=now,
            posted_at=now,
            txn_type="NEFT",
            status="POSTED",
        )
        db_session.add(txn)
        db_session.flush()

        # Deleting sender account must fail
        db_session.delete(acc1)
        with pytest.raises(IntegrityError):
            db_session.flush()


class TestUniquenessConstraints:
    """Verify idempotency and uniqueness constraints."""

    def test_source_records_idempotency_uniqueness(self, db_session):
        src = SourceSystem(id="SRC-1", name="Source 1")
        job = IngestionJob(
            id="job-1",
            source_system_id="SRC-1",
            received_at=datetime.now(UTC),
            state="PROCESSING",
            counts_json={},
        )
        db_session.add_all([src, job])
        db_session.flush()

        now = datetime.now(UTC)
        rec1 = SourceRecord(
            id="rec-01",
            ingestion_job_id="job-1",
            source_system_id="SRC-1",
            external_ref="EXT-1001",
            source_revision=1,
            payload_json={"test": 1},
            payload_hash="hash-1",
            received_at=now,
            record_status="PENDING",
        )
        db_session.add(rec1)
        db_session.flush()

        # Duplicate (source_system_id, external_ref, source_revision) must fail
        rec2 = SourceRecord(
            id="rec-02",
            ingestion_job_id="job-1",
            source_system_id="SRC-1",
            external_ref="EXT-1001",
            source_revision=1,
            payload_json={"test": 2},
            payload_hash="hash-2",
            received_at=now,
            record_status="PENDING",
        )
        db_session.add(rec2)
        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_outbox_events_dedup_uniqueness(self, db_session):
        now = datetime.now(UTC)
        evt1 = OutboxEvent(
            id="evt-01",
            event_type="TRANSACTION_POSTED",
            entity_id="txn-01",
            payload_json={"id": "txn-01"},
            payload_hash="hash-abc",
            status="PENDING",
            created_at=now,
        )
        db_session.add(evt1)
        db_session.flush()

        # Duplicate (event_type, entity_id, payload_hash) must fail
        evt2 = OutboxEvent(
            id="evt-02",
            event_type="TRANSACTION_POSTED",
            entity_id="txn-01",
            payload_json={"id": "txn-01"},
            payload_hash="hash-abc",
            status="PENDING",
            created_at=now,
        )
        db_session.add(evt2)
        with pytest.raises(IntegrityError):
            db_session.flush()


class TestDatabaseSeeding:
    """Verify that reference data and demo roles seed cleanly and idempotently."""

    def test_seed_database_repeatability(self, db_session):
        # Run 1
        counts1 = seed_database(db_session)
        assert counts1["roles"] == 5
        assert counts1["users"] == 5
        assert counts1["branches"] == 3
        assert counts1["accounts"] == 5
        assert counts1["workflows"] == 1
        assert counts1["rules"] == 1

        # Run 2 (idempotent; 0 new additions)
        counts2 = seed_database(db_session)
        assert counts2["roles"] == 0
        assert counts2["users"] == 0
        assert counts2["branches"] == 0
        assert counts2["accounts"] == 0
        assert counts2["workflows"] == 0
        assert counts2["rules"] == 0
