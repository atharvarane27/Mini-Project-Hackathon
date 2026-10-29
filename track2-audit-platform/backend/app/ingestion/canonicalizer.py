from __future__ import annotations

import uuid
from typing import Any

from app.db.models import Account, Branch, SourceRecord, SourceRecordTransaction, Transaction
from app.ingestion.normalizer import NormalizedRow


class Canonicalizer:
    """Transforms validated NormalizedRow into canonical 3NF database records."""

    def __init__(self, default_branch_id: str = "br-mum-01") -> None:
        self.default_branch_id = default_branch_id

    def ensure_accounts_exist(
        self,
        db_session: Any,
        sender_id: str,
        receiver_id: str,
        currency: str,
        branch_id: str | None = None,
    ) -> None:
        """Ensure accounts and branches exist before inserting transactions for RESTRICT FKs."""
        target_branch = branch_id or self.default_branch_id

        # Verify or create branch if needed
        branch = db_session.query(Branch).filter_by(id=target_branch).first()
        if not branch:
            branch = Branch(
                id=target_branch,
                code=target_branch.upper(),
                name=f"Branch {target_branch}",
            )
            db_session.add(branch)
            db_session.flush()

        # Sender account
        sender_acc = db_session.query(Account).filter_by(id=sender_id).first()
        if not sender_acc:
            sender_acc = Account(
                id=sender_id,
                branch_id=branch.id,
                currency=currency,
                masked_label=f"ACC-{sender_id[-8:] if len(sender_id) >= 8 else sender_id}",
            )
            db_session.add(sender_acc)

        # Receiver account
        receiver_acc = db_session.query(Account).filter_by(id=receiver_id).first()
        if not receiver_acc:
            receiver_acc = Account(
                id=receiver_id,
                branch_id=branch.id,
                currency=currency,
                masked_label=f"ACC-{receiver_id[-8:] if len(receiver_id) >= 8 else receiver_id}",
            )
            db_session.add(receiver_acc)

        db_session.flush()

    def build_records(
        self,
        row: NormalizedRow,
        job_id: str,
        source_system_id: str,
    ) -> tuple[SourceRecord, Transaction, SourceRecordTransaction]:
        """Build SourceRecord, Transaction, and junction link from NormalizedRow."""
        src_rec_id = f"src-{uuid.uuid4().hex[:16]}"
        txn_id = f"txn-{uuid.uuid4().hex[:16]}"

        source_rec = SourceRecord(
            id=src_rec_id,
            ingestion_job_id=job_id,
            source_system_id=source_system_id,
            external_ref=row.external_ref,
            source_revision=row.source_revision,
            payload_json=row.raw_payload,
            payload_hash=row.payload_hash,
            received_at=row.occurred_at,
            record_status="ACCEPTED",
        )

        canonical_txn = Transaction(
            id=txn_id,
            external_canonical_ref=f"CANON-{source_system_id}-{row.external_ref}-r{row.source_revision}",
            sender_account_id=row.sender_account_id,
            receiver_account_id=row.receiver_account_id,
            amount_minor=row.amount_minor,
            currency=row.currency,
            occurred_at=row.occurred_at,
            posted_at=row.posted_at,
            txn_type=row.txn_type,
            status=row.status,
        )

        junction = SourceRecordTransaction(
            source_record_id=src_rec_id,
            transaction_id=txn_id,
            link_type="CANONICAL",
        )

        return source_rec, canonical_txn, junction
