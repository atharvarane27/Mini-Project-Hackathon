"""Scaffold for backend/app/engines/reconciliation/journal_balance; implementation pending."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class JournalBalanceResult:
    status: str
    journal_id: str | None = None
    total_debit_minor: int = 0
    total_credit_minor: int = 0
    imbalance_minor: int = 0
    reason_code: str = ""


class JournalBalanceValidator:
    """Validate double-entry journal totals and produce the unbalanced status."""

    def evaluate(self, journal: dict[str, Any]) -> JournalBalanceResult:
        lines = journal.get("lines", []) if isinstance(journal, dict) else []
        total_debit_minor = 0
        total_credit_minor = 0
        for line in lines:
            if not isinstance(line, dict):
                continue
            total_debit_minor += int(line.get("debit_minor", 0) or 0)
            total_credit_minor += int(line.get("credit_minor", 0) or 0)
        imbalance = abs(total_debit_minor - total_credit_minor)
        if lines and total_debit_minor != total_credit_minor:
            return JournalBalanceResult(
                status="UNBALANCED_JOURNAL",
                journal_id=str(journal.get("id", "")),
                total_debit_minor=total_debit_minor,
                total_credit_minor=total_credit_minor,
                imbalance_minor=imbalance,
                reason_code="JOURNAL_IMBALANCE",
            )
        return JournalBalanceResult(
            status="BALANCED",
            journal_id=str(journal.get("id", "")),
            total_debit_minor=total_debit_minor,
            total_credit_minor=total_credit_minor,
            imbalance_minor=0,
            reason_code="BALANCED",
        )


def validate_journal_balance(journal: dict[str, Any]) -> JournalBalanceResult:
    return JournalBalanceValidator().evaluate(journal)
