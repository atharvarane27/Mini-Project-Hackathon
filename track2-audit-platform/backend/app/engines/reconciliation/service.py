"""Idempotent reconciliation run orchestration and persistence boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Iterable, Protocol, Sequence
from uuid import NAMESPACE_URL, uuid5

from app.schemas.common import deterministic_fingerprint

from .journal_balance import ReconciliationJournalLine, evaluate_journal_balances
from .matcher import (
    LedgerEntry,
    ReconciliationMatch,
    ReconciliationPolicy,
    ReconciliationStatus,
    reconcile_entries,
)


ALGORITHM_VERSION = "reconciliation-v1"


class ReconciliationRunConflict(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StoredReconciliationResult:
    result_id: str
    match: ReconciliationMatch

    def as_dict(self) -> dict[str, object]:
        return {"result_id": self.result_id, **self.match.as_dict()}


@dataclass(frozen=True, slots=True)
class StoredReconciliationRun:
    run_id: str
    run_key: str
    input_digest: str
    left_source_id: str
    right_source_id: str
    checkpoint: str
    policy_version: int
    cutoff_at: datetime
    results: tuple[StoredReconciliationResult, ...]
    status: str = "COMPLETED"

    def as_dict(self) -> dict[str, object]:
        counts: dict[str, int] = {}
        for result in self.results:
            name = result.match.status.value
            counts[name] = counts.get(name, 0) + 1
        return {
            "run_id": self.run_id,
            "status": self.status,
            "left_source_id": self.left_source_id,
            "right_source_id": self.right_source_id,
            "snapshot_checkpoint": self.checkpoint,
            "policy_version": self.policy_version,
            "cutoff_at": self.cutoff_at.isoformat(),
            "result_count": len(self.results),
            "classification_counts": counts,
            "algorithm_version": ALGORITHM_VERSION,
        }


@dataclass(frozen=True, slots=True)
class ReconciliationRunOutcome:
    run: StoredReconciliationRun
    replayed: bool


class ReconciliationRepository(Protocol):
    def save_completed_run(
        self,
        *,
        run_key: str,
        input_digest: str,
        left_source_id: str,
        right_source_id: str,
        checkpoint: str,
        policy_version: int,
        cutoff_at: datetime,
        matches: Sequence[ReconciliationMatch],
    ) -> ReconciliationRunOutcome: ...

    def get_run(self, run_id: str) -> StoredReconciliationRun | None: ...


def _entry_payload(entry: LedgerEntry) -> dict[str, object]:
    return {
        "transaction_id": entry.transaction_id,
        "source_id": entry.source_id,
        "external_reference": entry.external_reference,
        "sender_account_id": entry.sender_account_id,
        "receiver_account_id": entry.receiver_account_id,
        "amount_minor": entry.amount_minor,
        "currency": entry.currency,
        "occurred_at": entry.occurred_at,
        "status": entry.status,
    }


def run_reconciliation(
    *,
    left_source_id: str,
    right_source_id: str,
    left_entries: Iterable[LedgerEntry],
    right_entries: Iterable[LedgerEntry],
    journal_lines: Iterable[ReconciliationJournalLine],
    cutoff_at: datetime,
    checkpoint: str,
    policy: ReconciliationPolicy,
    repository: ReconciliationRepository,
) -> ReconciliationRunOutcome:
    left_source_id, right_source_id = left_source_id.strip(), right_source_id.strip()
    checkpoint = checkpoint.strip()
    if not left_source_id or not right_source_id or left_source_id == right_source_id:
        raise ValueError("two distinct source IDs are required")
    if not checkpoint:
        raise ValueError("checkpoint must not be blank")
    left, right, lines = tuple(left_entries), tuple(right_entries), tuple(journal_lines)
    matches = list(
        reconcile_entries(left, right, cutoff_at=cutoff_at, policy=policy)
    )
    for balance in evaluate_journal_balances(lines):
        if not balance.balanced:
            matches.append(
                ReconciliationMatch(
                    ReconciliationStatus.UNBALANCED_JOURNAL,
                    None,
                    None,
                    balance.variance_minor,
                    ("JOURNAL_DEBIT_CREDIT_VARIANCE",),
                    {
                        "journal_id": balance.journal_id,
                        "currency": balance.currency,
                        "debit_minor": balance.debit_minor,
                        "credit_minor": balance.credit_minor,
                    },
                )
            )
    run_key = deterministic_fingerprint(
        "reconciliation-run",
        {
            "left_source_id": left_source_id,
            "right_source_id": right_source_id,
            "checkpoint": checkpoint,
            "policy_version": policy.version,
            "cutoff_at": cutoff_at,
        },
    )
    input_digest = deterministic_fingerprint(
        "reconciliation-input",
        {
            "left": [_entry_payload(item) for item in sorted(left, key=lambda item: item.transaction_id)],
            "right": [_entry_payload(item) for item in sorted(right, key=lambda item: item.transaction_id)],
            "journals": [
                {
                    "journal_id": item.journal_id,
                    "line_id": item.line_id,
                    "debit_minor": item.debit_minor,
                    "credit_minor": item.credit_minor,
                    "currency": item.currency,
                }
                for item in sorted(lines, key=lambda item: (item.journal_id, item.line_id))
            ],
        },
    )
    return repository.save_completed_run(
        run_key=run_key,
        input_digest=input_digest,
        left_source_id=left_source_id,
        right_source_id=right_source_id,
        checkpoint=checkpoint,
        policy_version=policy.version,
        cutoff_at=cutoff_at,
        matches=matches,
    )


class InMemoryReconciliationRepository:
    """Thread-safe reference adapter with the same idempotency contract as SQL."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._runs_by_key: dict[str, StoredReconciliationRun] = {}
        self._runs_by_id: dict[str, StoredReconciliationRun] = {}

    def save_completed_run(
        self,
        *,
        run_key: str,
        input_digest: str,
        left_source_id: str,
        right_source_id: str,
        checkpoint: str,
        policy_version: int,
        cutoff_at: datetime,
        matches: Sequence[ReconciliationMatch],
    ) -> ReconciliationRunOutcome:
        with self._lock:
            existing = self._runs_by_key.get(run_key)
            if existing is not None:
                if existing.input_digest != input_digest:
                    raise ReconciliationRunConflict(
                        "run checkpoint was reused with different ledger input"
                    )
                return ReconciliationRunOutcome(existing, True)
            run_id = str(uuid5(NAMESPACE_URL, f"reconciliation-run:{run_key}"))
            results = tuple(
                StoredReconciliationResult(
                    str(uuid5(NAMESPACE_URL, f"{run_id}:result:{index}")), match
                )
                for index, match in enumerate(matches)
            )
            run = StoredReconciliationRun(
                run_id, run_key, input_digest, left_source_id, right_source_id,
                checkpoint, policy_version, cutoff_at, results,
            )
            self._runs_by_key[run_key] = run
            self._runs_by_id[run_id] = run
            return ReconciliationRunOutcome(run, False)

    def get_run(self, run_id: str) -> StoredReconciliationRun | None:
        with self._lock:
            return self._runs_by_id.get(run_id)
