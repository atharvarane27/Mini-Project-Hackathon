"""Deterministic one-to-one matching for independent ledger snapshots."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Iterable


class ReconciliationStatus(StrEnum):
    MATCHED = "MATCHED"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    FIELD_MISMATCH = "FIELD_MISMATCH"
    INTERNAL_ONLY = "INTERNAL_ONLY"
    COUNTERPART_ONLY = "COUNTERPART_ONLY"
    PENDING_LATE = "PENDING_LATE"
    AMBIGUOUS = "AMBIGUOUS"
    UNBALANCED_JOURNAL = "UNBALANCED_JOURNAL"


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    transaction_id: str
    source_id: str
    external_reference: str
    sender_account_id: str
    receiver_account_id: str
    amount_minor: int
    currency: str
    occurred_at: datetime
    status: str = "POSTED"

    def __post_init__(self) -> None:
        fields = (
            self.transaction_id, self.source_id, self.external_reference,
            self.sender_account_id, self.receiver_account_id, self.currency,
        )
        if not all(value.strip() for value in fields):
            raise ValueError("ledger identity fields must not be blank")
        if isinstance(self.amount_minor, bool) or not isinstance(self.amount_minor, int) or self.amount_minor <= 0:
            raise ValueError("amount_minor must be a positive integer")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        object.__setattr__(self, "currency", self.currency.strip().upper())
        object.__setattr__(self, "occurred_at", self.occurred_at.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class ReconciliationPolicy:
    version: int = 1
    max_posting_delta_minutes: int = 1440
    max_candidates_per_entry: int = 100

    def __post_init__(self) -> None:
        if self.version <= 0 or self.max_posting_delta_minutes < 0:
            raise ValueError("invalid reconciliation policy")
        if self.max_candidates_per_entry <= 0:
            raise ValueError("max_candidates_per_entry must be positive")


@dataclass(frozen=True, slots=True)
class ReconciliationMatch:
    status: ReconciliationStatus
    left_transaction_id: str | None
    right_transaction_id: str | None
    variance_minor: int
    reason_codes: tuple[str, ...]
    evidence: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return {
            "classification": self.status.value,
            "left_transaction_id": self.left_transaction_id,
            "right_transaction_id": self.right_transaction_id,
            "variance_minor": self.variance_minor,
            "reason_codes": list(self.reason_codes),
            "evidence": self.evidence,
        }


def _reference(entry: LedgerEntry) -> tuple[str, str]:
    return entry.external_reference.strip().casefold(), entry.currency


def _composite(entry: LedgerEntry) -> tuple[str, str, str, int, str]:
    return (
        entry.sender_account_id, entry.receiver_account_id, entry.currency,
        entry.amount_minor, entry.occurred_at.date().isoformat(),
    )


def _compare(
    left: LedgerEntry,
    right: LedgerEntry,
    policy: ReconciliationPolicy,
    *,
    reason: str,
) -> ReconciliationMatch:
    reasons = [reason]
    variance = left.amount_minor - right.amount_minor
    fields: list[str] = []
    if left.currency != right.currency:
        fields.append("CURRENCY")
    if left.sender_account_id != right.sender_account_id:
        fields.append("SENDER")
    if left.receiver_account_id != right.receiver_account_id:
        fields.append("RECEIVER")
    delta = abs(left.occurred_at - right.occurred_at)
    if delta > timedelta(minutes=policy.max_posting_delta_minutes):
        fields.append("POSTING_TIME")
    if fields:
        status = ReconciliationStatus.FIELD_MISMATCH
        reasons.extend(f"{field}_MISMATCH" for field in fields)
    elif variance:
        status = ReconciliationStatus.AMOUNT_MISMATCH
        reasons.append("AMOUNT_VARIANCE")
    else:
        status = ReconciliationStatus.MATCHED
    return ReconciliationMatch(
        status, left.transaction_id, right.transaction_id, variance, tuple(reasons),
        {
            "left_reference": left.external_reference,
            "right_reference": right.external_reference,
            "currency": left.currency,
            "posting_delta_seconds": int(delta.total_seconds()),
        },
    )


def _ambiguous(
    left: list[LedgerEntry], right: list[LedgerEntry], reason: str
) -> ReconciliationMatch:
    return ReconciliationMatch(
        ReconciliationStatus.AMBIGUOUS,
        left[0].transaction_id if len(left) == 1 else None,
        right[0].transaction_id if len(right) == 1 else None,
        0,
        (reason,),
        {
            "left_candidate_ids": sorted(item.transaction_id for item in left),
            "right_candidate_ids": sorted(item.transaction_id for item in right),
        },
    )


def reconcile_entries(
    left_entries: Iterable[LedgerEntry],
    right_entries: Iterable[LedgerEntry],
    *,
    cutoff_at: datetime,
    policy: ReconciliationPolicy | None = None,
) -> tuple[ReconciliationMatch, ...]:
    """Match each economic entry at most once and retain every unresolved row."""
    if cutoff_at.tzinfo is None or cutoff_at.utcoffset() is None:
        raise ValueError("cutoff_at must include a timezone")
    configured = policy or ReconciliationPolicy()
    left = sorted(
        (item for item in left_entries if item.status == "POSTED"),
        key=lambda item: (item.occurred_at, item.transaction_id),
    )
    right = sorted(
        (item for item in right_entries if item.status == "POSTED"),
        key=lambda item: (item.occurred_at, item.transaction_id),
    )
    if len({item.transaction_id for item in left}) != len(left):
        raise ValueError("duplicate left transaction ID")
    if len({item.transaction_id for item in right}) != len(right):
        raise ValueError("duplicate right transaction ID")

    left_by_ref: dict[tuple[str, str], list[LedgerEntry]] = defaultdict(list)
    right_by_ref: dict[tuple[str, str], list[LedgerEntry]] = defaultdict(list)
    for item in left:
        left_by_ref[_reference(item)].append(item)
    for item in right:
        right_by_ref[_reference(item)].append(item)

    consumed_left: set[str] = set()
    consumed_right: set[str] = set()
    results: list[ReconciliationMatch] = []
    for reference_key in sorted(set(left_by_ref) & set(right_by_ref)):
        left_group = left_by_ref[reference_key]
        right_group = right_by_ref[reference_key]
        if max(len(left_group), len(right_group)) > configured.max_candidates_per_entry:
            results.append(_ambiguous(left_group, right_group, "CANDIDATE_LIMIT_EXCEEDED"))
        elif len(left_group) != 1 or len(right_group) != 1:
            results.append(_ambiguous(left_group, right_group, "NON_UNIQUE_REFERENCE"))
        else:
            results.append(_compare(left_group[0], right_group[0], configured, reason="EXACT_REFERENCE"))
        consumed_left.update(item.transaction_id for item in left_group)
        consumed_right.update(item.transaction_id for item in right_group)

    remaining_left = [item for item in left if item.transaction_id not in consumed_left]
    remaining_right = [item for item in right if item.transaction_id not in consumed_right]
    left_by_composite: dict[tuple[str, str, str, int, str], list[LedgerEntry]] = defaultdict(list)
    right_by_composite: dict[tuple[str, str, str, int, str], list[LedgerEntry]] = defaultdict(list)
    for item in remaining_left:
        left_by_composite[_composite(item)].append(item)
    for item in remaining_right:
        right_by_composite[_composite(item)].append(item)
    for composite_key in sorted(set(left_by_composite) & set(right_by_composite)):
        left_group = left_by_composite[composite_key]
        right_group = right_by_composite[composite_key]
        if len(left_group) == 1 and len(right_group) == 1:
            results.append(_compare(left_group[0], right_group[0], configured, reason="COMPOSITE_KEY"))
        else:
            results.append(_ambiguous(left_group, right_group, "NON_UNIQUE_COMPOSITE_KEY"))
        consumed_left.update(item.transaction_id for item in left_group)
        consumed_right.update(item.transaction_id for item in right_group)

    cutoff = cutoff_at.astimezone(UTC)
    missing_entries = [
        *((item, ReconciliationStatus.INTERNAL_ONLY) for item in left),
        *((item, ReconciliationStatus.COUNTERPART_ONLY) for item in right),
    ]
    for item, missing_status in missing_entries:
        consumed = consumed_left if missing_status is ReconciliationStatus.INTERNAL_ONLY else consumed_right
        if item.transaction_id in consumed:
            continue
        pending = item.occurred_at > cutoff
        results.append(
            ReconciliationMatch(
                ReconciliationStatus.PENDING_LATE if pending else missing_status,
                item.transaction_id if missing_status is ReconciliationStatus.INTERNAL_ONLY else None,
                item.transaction_id if missing_status is ReconciliationStatus.COUNTERPART_ONLY else None,
                item.amount_minor if missing_status is ReconciliationStatus.INTERNAL_ONLY else -item.amount_minor,
                ("AFTER_CUTOFF" if pending else "NO_COUNTERPART",),
                {"reference": item.external_reference, "currency": item.currency},
            )
        )
    return tuple(sorted(results, key=lambda item: (
        item.left_transaction_id or "", item.right_transaction_id or "", item.status.value
    )))
