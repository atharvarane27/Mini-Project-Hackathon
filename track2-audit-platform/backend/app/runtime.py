"""Composition root for the API's shared application services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TextIO

from app.core.audit_writer import ActivityLedger
from app.core.auth import AuthService, UserIdentity, hash_password
from app.core.rbac import Role
from app.engines.circular.service import InMemoryCircularRunRepository
from app.engines.circular.dfs import find_cycle_candidates
from app.engines.circular.graph import TransferMultigraph
from app.engines.circular.temporal_validator import (
    CircularPolicy,
    CircularTransfer,
    CycleCandidate,
)
from app.engines.identity.inverted_index import InvertedIndex
from app.engines.identity.resolver import (
    IdentityRecord,
    InMemoryDuplicateRepository,
    analyze_duplicates,
)
from app.engines.reconciliation.journal_balance import ReconciliationJournalLine
from app.engines.reconciliation.matcher import LedgerEntry, ReconciliationPolicy
from app.engines.reconciliation.service import InMemoryReconciliationRepository
from app.engines.rules.service import InMemoryRuleRepository, RuleService
from app.engines.splitting.partition import SplittingPolicy, TransferEvent
from app.engines.splitting.service import InMemorySplittingRunRepository
from app.engines.workflow.service import InMemoryWorkflowRepository, WorkflowService
from app.ingestion.canonicalizer import InMemoryCanonicalRepository
from app.ingestion.service import (
    InMemoryIngestionRepository,
    IngestionJob,
    IngestionService,
)
from app.services.case_service import CaseService, InMemoryCaseRepository


@dataclass(slots=True)
class RuntimeServices:
    ingestion_repository: InMemoryIngestionRepository
    ingestion: IngestionService
    canonical: InMemoryCanonicalRepository
    duplicates: InMemoryDuplicateRepository
    reconciliation: InMemoryReconciliationRepository
    circular: InMemoryCircularRunRepository
    splitting: InMemorySplittingRunRepository
    rules: RuleService
    cases: CaseService
    workflows: WorkflowService
    auth: AuthService
    activity: ActivityLedger
    identity_index: InvertedIndex

    def ingest_csv(
        self,
        stream: TextIO,
        *,
        source_system: str,
        source_file: str,
        file_hash: str,
        idempotency_key: str,
        fail_after_batches: int | None = None,
    ) -> IngestionJob:
        job = self.ingestion.ingest(
            stream,
            source_system=source_system,
            source_file=source_file,
            file_hash=file_hash,
            idempotency_key=idempotency_key,
            fail_after_batches=fail_after_batches,
        )
        self.synchronize_projections()
        return job

    def synchronize_projections(self) -> None:
        identities: list[IdentityRecord] = []
        for stored in self.ingestion_repository.accepted():
            source = stored.transfer
            self.canonical.canonicalize(source)
            identities.append(
                IdentityRecord(
                    record_id=source.source_record_id,
                    transaction_reference=source.transaction_reference,
                    sender_account_id=source.sender_account_id,
                    receiver_account_id=source.receiver_account_id,
                    sender_name=source.sender_account_id,
                    receiver_name=source.receiver_account_id,
                    amount_minor=source.amount_minor,
                    currency=source.currency,
                    occurred_at=source.occurred_at,
                )
            )
        self.identity_index.rebuild(identities)
        analyze_duplicates(identities, self.identity_index, self.duplicates)

    @classmethod
    def create(cls, demo_admin_password: str) -> "RuntimeServices":
        ingestion_repository = InMemoryIngestionRepository()
        runtime = cls(
            ingestion_repository=ingestion_repository,
            ingestion=IngestionService(ingestion_repository),
            canonical=InMemoryCanonicalRepository(),
            duplicates=InMemoryDuplicateRepository(),
            reconciliation=InMemoryReconciliationRepository(),
            circular=InMemoryCircularRunRepository(),
            splitting=InMemorySplittingRunRepository(),
            rules=RuleService(InMemoryRuleRepository()),
            cases=CaseService(InMemoryCaseRepository()),
            workflows=WorkflowService(InMemoryWorkflowRepository()),
            auth=AuthService(
                (
                    UserIdentity(
                        "demo-admin",
                        "admin",
                        hash_password(demo_admin_password),
                        frozenset({Role.ADMIN}),
                    ),
                )
            ),
            activity=ActivityLedger(),
            identity_index=InvertedIndex(),
        )
        return runtime

    @staticmethod
    def reconciliation_policy(version: int) -> ReconciliationPolicy:
        if version != 1:
            raise KeyError(f"unknown reconciliation policy version {version}")
        return ReconciliationPolicy(version=version)

    @staticmethod
    def splitting_policy(version: int) -> SplittingPolicy:
        if version != 1:
            raise KeyError(f"unknown splitting policy version {version}")
        return SplittingPolicy(version=version)

    @staticmethod
    def circular_policy(version: int) -> CircularPolicy:
        if version != 1:
            raise KeyError(f"unknown circular policy version {version}")
        return CircularPolicy(version=version)

    def load_ledger(
        self, source_id: str, start: datetime, end: datetime, _checkpoint: str
    ) -> tuple[LedgerEntry, ...]:
        source_records = {
            item.transfer.source_record_id: item.transfer
            for item in self.ingestion_repository.accepted()
            if item.transfer.source_system == source_id
        }
        results: dict[str, LedgerEntry] = {}
        for transaction in self.canonical.downstream_snapshot():
            if not start <= transaction.occurred_at <= end:
                continue
            linked = next(
                (
                    source_records[source_record_id]
                    for source_record_id in transaction.source_record_ids
                    if source_record_id in source_records
                ),
                None,
            )
            if linked is None:
                continue
            results[transaction.transaction_id] = LedgerEntry(
                transaction.transaction_id,
                source_id,
                linked.transaction_reference,
                transaction.sender_account_id,
                transaction.receiver_account_id,
                transaction.amount_minor,
                transaction.currency,
                transaction.occurred_at,
                transaction.status,
            )
        return tuple(results[key] for key in sorted(results))

    def load_journals(
        self,
        left_source_id: str,
        right_source_id: str,
        start: datetime,
        end: datetime,
        _checkpoint: str,
    ) -> tuple[ReconciliationJournalLine, ...]:
        transaction_ids = {
            item.transaction_id
            for source_id in (left_source_id, right_source_id)
            for item in self.load_ledger(source_id, start, end, _checkpoint)
        }
        lines: list[ReconciliationJournalLine] = []
        for transaction_id in sorted(transaction_ids):
            for posting in self.canonical.journal_for(transaction_id):
                lines.append(
                    ReconciliationJournalLine(
                        posting.journal_id,
                        posting.posting_id,
                        posting.debit_minor,
                        posting.credit_minor,
                        posting.currency,
                    )
                )
        return tuple(lines)

    def load_transfers(
        self, start: datetime, end: datetime, _checkpoint: str
    ) -> tuple[TransferEvent, ...]:
        return tuple(
            TransferEvent(
                transaction.transaction_id,
                transaction.sender_account_id,
                transaction.receiver_account_id,
                transaction.amount_minor,
                transaction.currency,
                transaction.occurred_at,
                transaction.transaction_type,
                transaction.status,
                transaction.reversal_of_transaction_id is not None,
                transaction.reversal_of_transaction_id,
            )
            for transaction in self.canonical.downstream_snapshot()
            if start <= transaction.occurred_at <= end
        )

    def load_cycles(
        self, start: datetime, end: datetime, _checkpoint: str
    ) -> tuple[CycleCandidate, ...]:
        transfers = (
            CircularTransfer(
                transaction.transaction_id,
                transaction.sender_account_id,
                transaction.receiver_account_id,
                transaction.amount_minor,
                transaction.currency,
                transaction.occurred_at,
                transaction.status,
            )
            for transaction in self.canonical.downstream_snapshot()
            if start <= transaction.occurred_at <= end
        )
        return find_cycle_candidates(TransferMultigraph(transfers)).candidates
