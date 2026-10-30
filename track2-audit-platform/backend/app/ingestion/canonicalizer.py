from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Account,
    Branch,
    Finding,
    IngestionJob,
    Journal,
    JournalLine,
    SourceRecord,
    SourceRecordTransaction,
    SourceSystem,
    Transaction,
)
from app.ingestion.normalizer import NormalizedRow
from app.schemas.common import compute_finding_fingerprint
from app.schemas.detectors import FindingFacts, FindingType
from app.schemas.ingestion import CanonicalTransferEvent


@dataclass(frozen=True)
class CanonicalizationResult:
    """Result of canonicalizing a single normalized row."""

    source_record: SourceRecord
    transaction: Transaction
    junction: SourceRecordTransaction
    journal: Journal | None = None
    is_new: bool = True
    is_duplicate: bool = False
    is_ambiguous: bool = False


class Canonicalizer:
    """Transforms validated NormalizedRows into canonical 3NF database records.

    Invariants per PRD M01 & Phase P04:
    - Provenance: Bidirectional map between source_record <-> canonical transaction.
    - Determinism: external_canonical_ref = CANON-{source_system_id}-{external_ref}.
    - Accepted duplicate references collapse into one canonical transaction event.
    - Ambiguous duplicate references (conflicting financial facts) are quarantined for review.
    - Double-entry journals enforce paired debit/credit and exact money precision.
    - Unbalanced journal groups are flagged without deleting original postings.
    - Downstream snapshot exposes only unique accepted canonical transfers.
    - Corrections are reversible with full provenance preserved.
    """

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

    def ensure_provenance_entities_exist(
        self,
        db_session: Any,
        source_system_id: str,
        job_id: str,
    ) -> None:
        """Ensure SourceSystem and IngestionJob exist for RESTRICT FK constraints."""
        src_sys = db_session.query(SourceSystem).filter_by(id=source_system_id).first()
        if not src_sys:
            src_sys = SourceSystem(
                id=source_system_id,
                name=source_system_id,
                description=f"Auto-registered source system {source_system_id}",
            )
            db_session.add(src_sys)
            db_session.flush()

        job = db_session.query(IngestionJob).filter_by(id=job_id).first()
        if not job:
            job = IngestionJob(
                id=job_id,
                source_system_id=source_system_id,
                state="COMPLETED",
                counts_json={},
            )
            db_session.add(job)
            db_session.flush()

    def canonicalize_row(
        self,
        db_session: Session,
        row: NormalizedRow,
        job_id: str,
        source_system_id: str,
    ) -> CanonicalizationResult:
        """Deterministically canonicalize a row with duplicate collapse and ambiguity handling."""
        canon_ref = f"CANON-{source_system_id}-{row.external_ref}"

        # Ensure provenance entities exist
        self.ensure_provenance_entities_exist(db_session, source_system_id, job_id)

        # Ensure account entities exist
        self.ensure_accounts_exist(
            db_session,
            row.sender_account_id,
            row.receiver_account_id,
            row.currency,
            row.branch_id,
        )

        # Check if canonical transaction already exists for this external reference
        existing_txn = (
            db_session.query(Transaction)
            .filter_by(external_canonical_ref=canon_ref)
            .first()
        )

        src_rec_id = f"src-{uuid.uuid4().hex[:16]}"

        if existing_txn is not None:
            # Check financial match to distinguish accepted duplicate vs ambiguous conflict
            is_financial_match = (
                row.amount_minor == existing_txn.amount_minor
                and row.currency == existing_txn.currency
                and row.sender_account_id == existing_txn.sender_account_id
                and row.receiver_account_id == existing_txn.receiver_account_id
            )

            # Check if source record already exists for this revision
            existing_src = (
                db_session.query(SourceRecord)
                .filter_by(
                    source_system_id=source_system_id,
                    external_ref=row.external_ref,
                    source_revision=row.source_revision,
                )
                .first()
            )

            if is_financial_match:
                # Accepted duplicate reference: collapse to existing canonical event
                if existing_src is not None:
                    src_rec = existing_src
                else:
                    src_rec = SourceRecord(
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
                existing_junc = (
                    db_session.query(SourceRecordTransaction)
                    .filter_by(
                        source_record_id=src_rec.id,
                        transaction_id=existing_txn.id,
                    )
                    .first()
                )
                junction = existing_junc or SourceRecordTransaction(
                    source_record_id=src_rec.id,
                    transaction_id=existing_txn.id,
                    link_type="DUPLICATE_COLLAPSED",
                )
                return CanonicalizationResult(
                    source_record=src_rec,
                    transaction=existing_txn,
                    junction=junction,
                    journal=None,
                    is_new=False,
                    is_duplicate=True,
                    is_ambiguous=False,
                )
            else:
                # Ambiguous duplicate: conflicting facts for same external reference
                if existing_src is not None:
                    src_rec = existing_src
                    src_rec.record_status = "AMBIGUOUS"
                else:
                    src_rec = SourceRecord(
                        id=src_rec_id,
                        ingestion_job_id=job_id,
                        source_system_id=source_system_id,
                        external_ref=row.external_ref,
                        source_revision=row.source_revision,
                        payload_json=row.raw_payload,
                        payload_hash=row.payload_hash,
                        received_at=row.occurred_at,
                        record_status="AMBIGUOUS",
                    )
                existing_junc = (
                    db_session.query(SourceRecordTransaction)
                    .filter_by(
                        source_record_id=src_rec.id,
                        transaction_id=existing_txn.id,
                    )
                    .first()
                )
                junction = existing_junc or SourceRecordTransaction(
                    source_record_id=src_rec.id,
                    transaction_id=existing_txn.id,
                    link_type="AMBIGUOUS_DUPLICATE",
                )
                return CanonicalizationResult(
                    source_record=src_rec,
                    transaction=existing_txn,
                    junction=junction,
                    journal=None,
                    is_new=False,
                    is_duplicate=False,
                    is_ambiguous=True,
                )

        # New canonical event
        txn_id = f"txn-{uuid.uuid4().hex[:16]}"
        src_rec = SourceRecord(
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
            external_canonical_ref=canon_ref,
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

        # Double-entry paired journal lines
        target_branch = row.branch_id or self.default_branch_id
        jrn_ref = f"JRN-{source_system_id}-{row.external_ref}"
        journal, _, _ = self.store_journal_lines(
            db_session=db_session,
            branch_id=target_branch,
            journal_ref=jrn_ref,
            lines_data=[
                (row.sender_account_id, row.amount_minor, 0),
                (row.receiver_account_id, 0, row.amount_minor),
            ],
            posted_at=row.posted_at,
        )

        return CanonicalizationResult(
            source_record=src_rec,
            transaction=canonical_txn,
            junction=junction,
            journal=journal,
            is_new=True,
            is_duplicate=False,
            is_ambiguous=False,
        )

    def build_records(
        self,
        row: NormalizedRow,
        job_id: str,
        source_system_id: str,
        db_session: Session | None = None,
    ) -> tuple[SourceRecord, Transaction, SourceRecordTransaction]:
        """Build SourceRecord, Transaction, and junction link from NormalizedRow.

        Supports both standalone generation and session-aware duplicate collapsing.
        """
        if db_session is not None:
            res = self.canonicalize_row(db_session, row, job_id, source_system_id)
            return res.source_record, res.transaction, res.junction

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
            external_canonical_ref=f"CANON-{source_system_id}-{row.external_ref}",
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

    def store_journal_lines(
        self,
        db_session: Session,
        branch_id: str,
        journal_ref: str,
        lines_data: list[tuple[str, int, int]],
        posted_at: datetime | None = None,
    ) -> tuple[Journal, bool, Finding | None]:
        """Store journal lines with paired debit/credit and exact money precision.

        Validates double-entry balance (sum debit == sum credit).
        Flags unbalanced groups without deleting original postings.
        """
        # Ensure branch exists
        branch = db_session.query(Branch).filter_by(id=branch_id).first()
        if not branch:
            branch = Branch(id=branch_id, code=branch_id.upper(), name=f"Branch {branch_id}")
            db_session.add(branch)
            db_session.flush()

        jrn_time = posted_at or datetime.now(UTC)
        journal = db_session.query(Journal).filter_by(journal_ref=journal_ref).first()
        if not journal:
            journal = Journal(
                id=f"jrn-{uuid.uuid4().hex[:16]}",
                branch_id=branch_id,
                posted_at=jrn_time,
                journal_ref=journal_ref,
                status="POSTED",
            )
            db_session.add(journal)
            db_session.flush()

        # Add lines
        total_debit = 0
        total_credit = 0
        for acc_id, debit, credit in lines_data:
            # Ensure account exists
            acc = db_session.query(Account).filter_by(id=acc_id).first()
            if not acc:
                acc = Account(
                    id=acc_id,
                    branch_id=branch_id,
                    currency="INR",
                    masked_label=f"ACC-{acc_id[-8:] if len(acc_id) >= 8 else acc_id}",
                )
                db_session.add(acc)
                db_session.flush()

            jline = JournalLine(
                id=f"jnl-{uuid.uuid4().hex[:16]}",
                journal_id=journal.id,
                account_id=acc_id,
                debit_minor=debit,
                credit_minor=credit,
            )
            db_session.add(jline)
            total_debit += debit
            total_credit += credit

        # Double-entry balance check: sum(debit) == sum(credit)
        is_balanced = (total_debit == total_credit) and (total_debit > 0)
        finding: Finding | None = None

        if is_balanced:
            journal.status = "POSTED"
        else:
            # Flag unbalanced group without deleting original postings
            journal.status = "UNBALANCED"
            imbalance = abs(total_debit - total_credit)
            finding_fp = compute_finding_fingerprint("UNBALANCED_JOURNAL", journal.id, imbalance)

            finding = db_session.query(Finding).filter_by(fingerprint=finding_fp).first()
            if not finding:
                facts = FindingFacts(
                    Balance_Anomaly_Flag=True,
                    Reconciliation_Variance_Minor=imbalance,
                    Severity="HIGH",
                )
                evidence = {
                    "journal_id": journal.id,
                    "journal_ref": journal.journal_ref,
                    "branch_id": journal.branch_id,
                    "total_debit_minor": total_debit,
                    "total_credit_minor": total_credit,
                    "imbalance_minor": imbalance,
                    "line_count": len(lines_data),
                    "facts": facts.model_dump(),
                }
                finding = Finding(
                    id=f"fnd-{uuid.uuid4().hex[:16]}",
                    finding_type=FindingType.UNBALANCED_JOURNAL.value,
                    fingerprint=finding_fp,
                    detector_config_id=None,
                    algorithm_version="v1.0",
                    status="FLAGGED_FOR_REVIEW",
                    evidence_json=evidence,
                    created_at=datetime.now(UTC),
                )
                db_session.add(finding)

        db_session.flush()
        return journal, is_balanced, finding

    def apply_correction(
        self,
        db_session: Session,
        transaction_id: str,
        correction_source_record: SourceRecord,
        new_status: str = "REVERSED",
        link_type: str = "CORRECTION",
    ) -> tuple[Transaction, SourceRecordTransaction]:
        """Apply a correction/reversal to a transaction with reversible provenance."""
        self.ensure_provenance_entities_exist(
            db_session,
            correction_source_record.source_system_id,
            correction_source_record.ingestion_job_id,
        )
        txn = db_session.query(Transaction).filter_by(id=transaction_id).first()
        if not txn:
            raise ValueError(f"Transaction '{transaction_id}' not found")

        txn.status = new_status
        junction = SourceRecordTransaction(
            source_record_id=correction_source_record.id,
            transaction_id=txn.id,
            link_type=link_type,
        )
        db_session.add(junction)
        db_session.flush()
        return txn, junction

    def revert_correction(
        self,
        db_session: Session,
        transaction_id: str,
        revert_source_record: SourceRecord | None = None,
        restored_status: str = "POSTED",
    ) -> tuple[Transaction, SourceRecordTransaction | None]:
        """Revert a previous correction, restoring status with complete audit history."""
        txn = db_session.query(Transaction).filter_by(id=transaction_id).first()
        if not txn:
            raise ValueError(f"Transaction '{transaction_id}' not found")

        txn.status = restored_status
        junction: SourceRecordTransaction | None = None
        if revert_source_record is not None:
            self.ensure_provenance_entities_exist(
                db_session,
                revert_source_record.source_system_id,
                revert_source_record.ingestion_job_id,
            )
            junction = SourceRecordTransaction(
                source_record_id=revert_source_record.id,
                transaction_id=txn.id,
                link_type="CORRECTION_REVERTED",
            )
            db_session.add(junction)

        db_session.flush()
        return txn, junction

    def get_downstream_snapshot(
        self,
        db_session: Session,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        currency: str | None = None,
    ) -> list[CanonicalTransferEvent]:
        """Expose a downstream snapshot of unique accepted canonical transfers.

        Guarantees that repeated transport copies and retries never add extra transfers.
        """
        stmt = (
            select(Transaction)
            .filter(Transaction.status == "POSTED")
            .order_by(Transaction.occurred_at.asc(), Transaction.id.asc())
        )

        if start_at is not None:
            stmt = stmt.filter(Transaction.occurred_at >= start_at)
        if end_at is not None:
            stmt = stmt.filter(Transaction.occurred_at <= end_at)
        if currency is not None:
            stmt = stmt.filter(Transaction.currency == currency)

        transactions = db_session.scalars(stmt).all()

        events: list[CanonicalTransferEvent] = []
        for t in transactions:
            occurred = t.occurred_at
            if occurred.tzinfo is None:
                occurred = occurred.replace(tzinfo=UTC)

            events.append(
                CanonicalTransferEvent(
                    transaction_id=t.id,
                    sender=t.sender_account_id,
                    receiver=t.receiver_account_id,
                    amount_minor=t.amount_minor,
                    currency=t.currency,
                    occurred_at=occurred,
                    status=t.status,
                    checkpoint=f"chk-{t.id}",
                )
            )
        return events
