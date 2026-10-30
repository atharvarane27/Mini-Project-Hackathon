"""Currency-aware double-entry journal validation for reconciliation."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class ReconciliationJournalLine:
    journal_id: str
    line_id: str
    debit_minor: int
    credit_minor: int
    currency: str

    def __post_init__(self) -> None:
        if not self.journal_id.strip() or not self.line_id.strip():
            raise ValueError("journal identifiers must not be blank")
        if self.debit_minor < 0 or self.credit_minor < 0:
            raise ValueError("journal amounts must be nonnegative")
        if (self.debit_minor == 0) == (self.credit_minor == 0):
            raise ValueError("a line must have exactly one positive side")


@dataclass(frozen=True, slots=True)
class JournalBalance:
    journal_id: str
    currency: str
    debit_minor: int
    credit_minor: int

    @property
    def variance_minor(self) -> int:
        return self.debit_minor - self.credit_minor

    @property
    def balanced(self) -> bool:
        return self.variance_minor == 0


def evaluate_journal_balances(
    lines: Iterable[ReconciliationJournalLine],
) -> tuple[JournalBalance, ...]:
    grouped: dict[tuple[str, str], list[ReconciliationJournalLine]] = defaultdict(list)
    currencies: dict[str, set[str]] = defaultdict(set)
    for line in lines:
        currency = line.currency.strip().upper()
        grouped[(line.journal_id, currency)].append(line)
        currencies[line.journal_id].add(currency)
    if any(len(values) != 1 for values in currencies.values()):
        raise ValueError("one journal cannot contain multiple currencies")
    return tuple(
        JournalBalance(
            journal_id, currency,
            sum(item.debit_minor for item in items),
            sum(item.credit_minor for item in items),
        )
        for (journal_id, currency), items in sorted(grouped.items())
    )
