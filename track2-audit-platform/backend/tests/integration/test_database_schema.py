"""P02 normalized schema, constraints, and session acceptance tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import (
    Account,
    Base,
    Branch,
    CanonicalTransaction,
    OutboxEvent,
    SourceRecord,
    SourceRecordLink,
    SourceSystem,
)
from app.db.session import (
    create_database_engine,
    create_session_factory,
    transaction_session,
)


NOW = datetime(2026, 10, 30, tzinfo=UTC)


def sqlite_engine() -> Engine:
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record) -> None:  # type: ignore[no-untyped-def]
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return engine


def seed_financial_graph(session: Session) -> tuple[SourceRecord, CanonicalTransaction]:
    branch = Branch(id="branch", branch_code="B001", name="Main")
    left = Account(
        id="left", branch_id="branch", account_number="A1",
        account_name="Left", currency="INR",
    )
    right = Account(
        id="right", branch_id="branch", account_number="A2",
        account_name="Right", currency="INR",
    )
    system = SourceSystem(id="system", code="LEDGER", name="Ledger")
    source = SourceRecord(
        id="source", source_system_id="system", external_id="EXT-1", revision=1,
        payload_hash="a" * 64, raw_payload={}, received_at=NOW,
    )
    transaction = CanonicalTransaction(
        id="transaction", transaction_reference="TXN-1", sender_account_id="left",
        receiver_account_id="right", amount_minor=100, currency="INR",
        occurred_at=NOW, transaction_type="TRANSFER", status="POSTED",
        fingerprint="b" * 64,
    )
    session.add_all((branch, system))
    session.flush()
    session.add_all((left, right, source))
    session.flush()
    session.add(transaction)
    session.flush()
    session.add(SourceRecordLink(source_record_id="source", transaction_id="transaction"))
    session.flush()
    return source, transaction


def test_metadata_contains_normalized_tables_and_no_evidence_cascade_delete() -> None:
    engine = sqlite_engine()
    tables = set(inspect(engine).get_table_names())
    assert {
        "branches", "accounts", "source_records", "canonical_transactions",
        "source_record_links", "journals", "journal_lines", "detector_runs",
        "findings", "finding_evidence", "audit_cases", "outbox_events",
        "workflow_dependencies", "users", "roles", "activity_log",
    } <= tables
    evidence_tables = {
        "source_record_links", "journal_lines", "finding_evidence",
        "case_findings", "activity_log",
    }
    for table_name in evidence_tables:
        for foreign_key in Base.metadata.tables[table_name].foreign_keys:
            assert foreign_key.ondelete != "CASCADE"


def test_financial_checks_uniqueness_and_restrictive_provenance() -> None:
    engine = sqlite_engine()
    with Session(engine) as session:
        source, _ = seed_financial_graph(session)
        session.commit()
        session.delete(source)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        duplicate = SourceRecord(
            source_system_id="system", external_id="EXT-1", revision=1,
            payload_hash="c" * 64, raw_payload={}, received_at=NOW,
        )
        session.add(duplicate)
        with pytest.raises(IntegrityError):
            session.commit()


def test_outbox_logical_identity_is_unique() -> None:
    engine = sqlite_engine()
    with Session(engine) as session:
        fields = {
            "event_type": "CASE_QUEUED", "entity_id": "case-1",
            "entity_version": 1, "payload": {}, "payload_hash": "d" * 64,
            "status": "PENDING", "attempt_count": 0, "available_at": NOW,
        }
        session.add_all((OutboxEvent(**fields), OutboxEvent(**fields)))
        with pytest.raises(IntegrityError):
            session.commit()


def test_transaction_scoped_session_commits_and_rolls_back() -> None:
    settings = Settings(
        "test", "test", "WARNING", "sqlite:///:memory:", 5, 5, 30, 1800
    )
    engine = create_database_engine(settings)
    Base.metadata.create_all(engine)
    factory = create_session_factory(engine)
    with transaction_session(factory) as session:
        session.add(Branch(id="committed", branch_code="C", name="Committed"))
    with factory() as session:
        assert session.get(Branch, "committed") is not None
    with pytest.raises(RuntimeError):
        with transaction_session(factory) as session:
            session.add(Branch(id="rolled-back", branch_code="R", name="Rollback"))
            raise RuntimeError("stop")
    with factory() as session:
        assert session.get(Branch, "rolled-back") is None
