"""Integration tests for duplicate classification and evidence generation."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Account, Base, Branch, Transaction
from app.db.session import get_db
from app.engines.identity.resolver import DuplicateResolver
from app.main import app


class TestDuplicateResolverIntegration:
    def test_typo_matches_as_candidate(self) -> None:
        resolver = DuplicateResolver(
            index_fields=["payee_name", "amount_minor"],
            phonetic_field="payee_name",
            text_field="payee_name",
            amount_field="amount_minor",
            similarity_threshold=0.75,
        )
        resolver.add_record("r1", {"payee_name": "John Doe", "amount_minor": 50000, "sender_account_id": "A1", "receiver_account_id": "B1"})
        resolver.add_record("r2", {"payee_name": "Jon Doe", "amount_minor": 50000, "sender_account_id": "A1", "receiver_account_id": "B1"})

        results = resolver.resolve("r1", {"payee_name": "John Doe", "amount_minor": 50000, "sender_account_id": "A1", "receiver_account_id": "B1"})
        assert any(item.record_id_b == "r2" and item.result == "CANDIDATE" for item in results)
        assert results[0].evidence.algorithm_version == "p06-levenshtein-v1"

    def test_reversal_is_non_match(self) -> None:
        resolver = DuplicateResolver(
            index_fields=["payee_name", "amount_minor"],
            phonetic_field="payee_name",
            text_field="payee_name",
            amount_field="amount_minor",
            similarity_threshold=0.75,
        )
        resolver.add_record("r1", {"payee_name": "Alice Smith", "amount_minor": 1000, "sender_account_id": "A1", "receiver_account_id": "B1"})
        resolver.add_record("r2", {"payee_name": "Alice Smith", "amount_minor": -1000, "sender_account_id": "B1", "receiver_account_id": "A1"})

        results = resolver.resolve("r1", {"payee_name": "Alice Smith", "amount_minor": 1000, "sender_account_id": "A1", "receiver_account_id": "B1"})
        assert any(item.record_id_b == "r2" and item.result == "NON_MATCH" for item in results)

    def test_mirror_transfer_is_non_match(self) -> None:
        resolver = DuplicateResolver(
            index_fields=["payee_name", "amount_minor"],
            phonetic_field="payee_name",
            text_field="payee_name",
            amount_field="amount_minor",
            similarity_threshold=0.75,
        )
        resolver.add_record("r1", {"payee_name": "Acme Rent", "amount_minor": 2500, "sender_account_id": "A1", "receiver_account_id": "B1"})
        resolver.add_record("r2", {"payee_name": "Acme Rent", "amount_minor": 2500, "sender_account_id": "B1", "receiver_account_id": "A1"})

        results = resolver.resolve("r1", {"payee_name": "Acme Rent", "amount_minor": 2500, "sender_account_id": "A1", "receiver_account_id": "B1"})
        assert any(item.record_id_b == "r2" and item.result == "NON_MATCH" for item in results)

    def test_empty_text_same_amount_is_not_exact(self) -> None:
        resolver = DuplicateResolver(
            index_fields=["payee_name", "amount_minor"],
            phonetic_field="payee_name",
            text_field="payee_name",
            amount_field="amount_minor",
            similarity_threshold=0.75,
        )
        resolver.add_record("r1", {"payee_name": "", "amount_minor": 50000, "sender_account_id": "A1", "receiver_account_id": "B1"})
        resolver.add_record("r2", {"payee_name": "", "amount_minor": 50000, "sender_account_id": "A1", "receiver_account_id": "B1"})

        results = resolver.resolve("r1", {"payee_name": "", "amount_minor": 50000, "sender_account_id": "A1", "receiver_account_id": "B1"})
        assert all(item.result != "EXACT" for item in results)

    def test_recurring_payment_matches_as_candidate(self) -> None:
        resolver = DuplicateResolver(
            index_fields=["payee_name", "amount_minor"],
            phonetic_field="payee_name",
            text_field="payee_name",
            amount_field="amount_minor",
            similarity_threshold=0.75,
        )
        resolver.add_record("r1", {"payee_name": "Monthly Utility Payment", "amount_minor": 4200, "sender_account_id": "A1", "receiver_account_id": "B1"})
        resolver.add_record("r2", {"payee_name": "Monthley Utility Payment", "amount_minor": 4200, "sender_account_id": "A1", "receiver_account_id": "B1"})

        results = resolver.resolve("r1", {"payee_name": "Monthly Utility Payment", "amount_minor": 4200, "sender_account_id": "A1", "receiver_account_id": "B1"})
        assert any(item.record_id_b == "r2" and item.result == "CANDIDATE" for item in results)

    def test_bucket_skew_keeps_comparison_count_pounded(self) -> None:
        resolver = DuplicateResolver(
            index_fields=["payee_name", "amount_minor"],
            phonetic_field="payee_name",
            text_field="payee_name",
            amount_field="amount_minor",
            similarity_threshold=0.7,
        )
        for idx in range(50):
            resolver.add_record(f"r{idx}", {"payee_name": "Alice Smith", "amount_minor": 1000, "sender_account_id": "A1", "receiver_account_id": "B1"})

        results = resolver.resolve("r0", {"payee_name": "Alice Smith", "amount_minor": 1000, "sender_account_id": "A1", "receiver_account_id": "B1"})
        assert len(results) < 50
        assert all(item.levenshtein_distance <= 3 for item in results if item.result in {"CANDIDATE", "EXACT"})

    def test_duplicate_api_returns_seeded_db_rows(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(engine, "connect")
        def _fk_pragma(dbapi_conn, _rec):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        Base.metadata.create_all(bind=engine)
        factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

        def override_get_db() -> Generator[Session, None, None]:
            session = factory()
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_db] = override_get_db
        try:
            with factory() as session:
                session.add_all(
                    [
                        Branch(id="branch-1", code="BR1", name="Main Branch"),
                        Account(
                            id="A1",
                            branch_id="branch-1",
                            currency="INR",
                            masked_label="A1",
                        ),
                        Account(
                            id="B1",
                            branch_id="branch-1",
                            currency="INR",
                            masked_label="B1",
                        ),
                    ]
                )
                session.commit()

            with factory() as session:
                session.query(Transaction).delete()
                session.add_all(
                    [
                        Transaction(
                            id="txn-1",
                            external_canonical_ref="CANON-SRC-REF-1",
                            sender_account_id="A1",
                            receiver_account_id="B1",
                            amount_minor=50000,
                            currency="INR",
                            occurred_at=datetime(2026, 10, 30, 9, 0, tzinfo=UTC),
                            posted_at=datetime(2026, 10, 30, 9, 0, tzinfo=UTC),
                            txn_type="TRANSFER",
                            status="POSTED",
                        ),
                        Transaction(
                            id="txn-2",
                            external_canonical_ref="CANON-SRC-REF-2",
                            sender_account_id="A1",
                            receiver_account_id="B1",
                            amount_minor=50000,
                            currency="INR",
                            occurred_at=datetime(2026, 10, 30, 9, 1, tzinfo=UTC),
                            posted_at=datetime(2026, 10, 30, 9, 1, tzinfo=UTC),
                            txn_type="TRANSFER",
                            status="POSTED",
                        ),
                    ]
                )
                session.commit()

            client = TestClient(app)
            response = client.get("/api/v1/duplicates?limit=10")
            assert response.status_code == 200
            payload = response.json()
            assert "data" in payload
            assert "meta" in payload
            assert payload["meta"]["limit"] == 10
            assert isinstance(payload["data"], list)
            assert len(payload["data"]) >= 1
        finally:
            app.dependency_overrides.clear()
            engine.dispose()
