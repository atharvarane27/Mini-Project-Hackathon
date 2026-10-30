"""Scaffold for backend/app/engines/reconciliation/service; implementation pending."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

from app.engines.reconciliation.matcher import ReconciliationMatch, ReconciliationMatcher, ReconciliationStatus, compute_run_id
from app.engines.reconciliation.journal_balance import JournalBalanceValidator


@dataclass(frozen=True)
class ReconciliationRunResult:
    run_id: str
    status: str
    matches: list[ReconciliationMatch] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)


class ReconciliationService:
    """Orchestrates one reconciliation run across left/right ledgers and journal validation."""

    def __init__(self, *, matcher: ReconciliationMatcher | None = None) -> None:
        self.matcher = matcher or ReconciliationMatcher()
        self.journal_validator = JournalBalanceValidator()

    def build_run_id(
        self,
        *,
        source_left_id: str,
        source_right_id: str,
        start_at: datetime | str,
        cutoff_at: datetime | str,
        currency: str,
        policy_version: str,
        input_checkpoint: str,
    ) -> str:
        return compute_run_id(
            source_left_id=source_left_id,
            source_right_id=source_right_id,
            start_at=start_at,
            cutoff_at=cutoff_at,
            currency=currency,
            policy_version=policy_version,
            input_checkpoint=input_checkpoint,
        )

    def reconcile(
        self,
        *,
        left_records: Iterable[dict[str, Any]],
        right_records: Iterable[dict[str, Any]],
        source_left_id: str,
        source_right_id: str,
        start_at: datetime | str,
        cutoff_at: datetime | str,
        currency: str,
        policy_version: str,
        input_checkpoint: str,
    ) -> ReconciliationRunResult:
        run_id = self.build_run_id(
            source_left_id=source_left_id,
            source_right_id=source_right_id,
            start_at=start_at,
            cutoff_at=cutoff_at,
            currency=currency,
            policy_version=policy_version,
            input_checkpoint=input_checkpoint,
        )
        matches = self.matcher.match_records(
            left_records,
            right_records,
            cutoff_at=cutoff_at if isinstance(cutoff_at, datetime) else None,
            currency=currency,
        )
        summary = Counter(status.value if hasattr(status, "value") else str(status) for status in (item.status for item in matches))
        return ReconciliationRunResult(
            run_id=run_id,
            status="COMPLETED",
            matches=list(matches),
            summary={k: int(v) for k, v in summary.items()},
        )

    def validate_journal(self, journal: dict[str, Any]) -> dict[str, Any]:
        result = self.journal_validator.evaluate(journal)
        return {
            "status": result.status,
            "journal_id": result.journal_id,
            "total_debit_minor": result.total_debit_minor,
            "total_credit_minor": result.total_credit_minor,
            "imbalance_minor": result.imbalance_minor,
            "reason_code": result.reason_code,
        }
