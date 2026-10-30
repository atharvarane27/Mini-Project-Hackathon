"""Deterministic reconciliation matcher for exact-reference matching, composite keys, candidate fallback, amount mismatches, late cutoff records, and ambiguous cases per the P07 contract."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Iterable

from app.engines.identity.resolver import DuplicateResolver


class ReconciliationStatus(StrEnum):
    MATCHED = "MATCHED"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    FIELD_MISMATCH = "FIELD_MISMATCH"
    INTERNAL_ONLY = "INTERNAL_ONLY"
    COUNTERPART_ONLY = "COUNTERPART_ONLY"
    PENDING_LATE = "PENDING_LATE"
    AMBIGUOUS = "AMBIGUOUS"
    UNBALANCED_JOURNAL = "UNBALANCED_JOURNAL"


@dataclass(frozen=True)
class ReconciliationMatch:
    status: ReconciliationStatus
    left_record_id: str | None = None
    right_record_id: str | None = None
    variance_minor: int = 0
    reason_code: str = ""
    left_amount_minor: int | None = None
    right_amount_minor: int | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


def _normalize_ref(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"[^a-z0-9]+", "", str(value).strip().lower())


def _amount_minor(record: dict[str, Any]) -> int | None:
    for key in ("amount_minor", "amount", "minor_amount"):
        value = record.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _record_id(record: dict[str, Any]) -> str:
    for key in ("id", "record_id", "transaction_id", "source_record_id"):
        value = record.get(key)
        if value is not None:
            return str(value)
    return "record-unknown"


def _reference(record: dict[str, Any]) -> str:
    for key in ("external_ref", "reference", "external_reference", "ref", "journal_ref"):
        value = record.get(key)
        if value is not None:
            return str(value)
    return ""


def _source(record: dict[str, Any]) -> str | None:
    for key in ("source", "source_system", "source_name", "ledger", "source_id"):
        value = record.get(key)
        if value is not None:
            return str(value)
    return None


def _currency(record: dict[str, Any]) -> str | None:
    value = record.get("currency")
    if value is None:
        return None
    return str(value).upper()


def _coerce_utc_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            text = str(value).strip()
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _occurred_at(record: dict[str, Any]) -> datetime | None:
    for key in ("occurred_at", "posted_at", "created_at", "timestamp"):
        value = record.get(key)
        dt = _coerce_utc_datetime(value)
        if dt is not None:
            return dt
    return None


def _record_in_window(record: dict[str, Any], *, start_at: datetime | None, cutoff_at: datetime | None) -> bool:
    occurred_at = _occurred_at(record)
    if occurred_at is None:
        return True
    if start_at is not None and occurred_at < start_at:
        return False
    if cutoff_at is not None and occurred_at > cutoff_at:
        return True
    return True


def _same_source(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_source = _source(left)
    right_source = _source(right)
    if left_source is None or right_source is None:
        return True
    return left_source == right_source


def _is_reversal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_amount = _amount_minor(left)
    right_amount = _amount_minor(right)
    if left_amount is None or right_amount is None:
        return False
    return left_amount == -right_amount


class ReconciliationMatcher:
    ALGORITHM_VERSION = "p07-reconciliation-v1"

    def __init__(self, *, similarity_threshold: float = 0.8) -> None:
        self.similarity_threshold = float(similarity_threshold)

    def _new_resolver(self) -> DuplicateResolver:
        return DuplicateResolver(
            index_fields=["external_ref", "reference", "amount_minor"],
            phonetic_field="external_ref",
            text_field="external_ref",
            amount_field="amount_minor",
            similarity_threshold=self.similarity_threshold,
        )

    def match_records(
        self,
        left_records: Iterable[dict[str, Any]],
        right_records: Iterable[dict[str, Any]],
        *,
        start_at: datetime | str | None = None,
        cutoff_at: datetime | None = None,
        currency: str | None = None,
    ) -> list[ReconciliationMatch]:
        start_dt = _coerce_utc_datetime(start_at) if isinstance(start_at, str | datetime) else start_at
        cutoff_dt = _coerce_utc_datetime(cutoff_at) if isinstance(cutoff_at, str | datetime) else cutoff_at

        resolver = self._new_resolver()
        left = [dict(item) for item in left_records]
        right = [dict(item) for item in right_records]
        right_by_ref: dict[str, list[dict[str, Any]]] = defaultdict(list)
        right_by_compound: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for record in right:
            occurred_at = _occurred_at(record)
            if start_dt is not None and occurred_at is not None and occurred_at < start_dt:
                continue
            if cutoff_dt is not None and occurred_at is not None and occurred_at > cutoff_dt:
                pass
            ref = _reference(record)
            if ref:
                right_by_ref[_normalize_ref(ref)].append(record)
            compound = self._compound_key(record)
            if compound:
                right_by_compound[compound].append(record)
            resolver.add_record(_record_id(record), record)

        consumed_left: set[str] = set()
        consumed_right: set[str] = set()
        results: list[ReconciliationMatch] = []

        for left_record in left:
            left_id = _record_id(left_record)
            if left_id in consumed_left:
                continue
            left_occurred = _occurred_at(left_record)
            if start_dt is not None and left_occurred is not None and left_occurred < start_dt:
                continue
            if cutoff_dt is not None and left_occurred is not None and left_occurred > cutoff_dt:
                results.append(
                    ReconciliationMatch(
                        status=ReconciliationStatus.PENDING_LATE,
                        left_record_id=left_id,
                        right_record_id=None,
                        variance_minor=0,
                        reason_code="AFTER_CUTOFF",
                        left_amount_minor=_amount_minor(left_record),
                        evidence={"cutoff_at": cutoff_dt.isoformat(), "occurred_at": left_occurred.isoformat()},
                    )
                )
                consumed_left.add(left_id)
                continue

            candidate_matches = self._candidate_records(left_record, right_by_ref, right_by_compound, right)
            if not candidate_matches:
                results.append(
                    ReconciliationMatch(
                        status=ReconciliationStatus.INTERNAL_ONLY,
                        left_record_id=left_id,
                        right_record_id=None,
                        variance_minor=0,
                        reason_code="NO_MATCH_FOUND",
                        left_amount_minor=_amount_minor(left_record),
                        evidence={"left_reference": _reference(left_record), "currency": _currency(left_record)},
                    )
                )
                consumed_left.add(left_id)
                continue

            if cutoff_dt is not None:
                non_late = [
                    candidate for candidate in candidate_matches
                    if _record_id(candidate) not in consumed_right
                    and not (
                        (_occurred_at(candidate) is not None) and (_occurred_at(candidate) > cutoff_dt)
                    )
                ]
                if non_late:
                    candidate_matches = non_late
                else:
                    late_candidates = [
                        candidate for candidate in candidate_matches
                        if _record_id(candidate) not in consumed_right and _occurred_at(candidate) is not None and _occurred_at(candidate) > cutoff_dt
                    ]
                    if late_candidates:
                        late_candidate = late_candidates[0]
                        results.append(
                            ReconciliationMatch(
                                status=ReconciliationStatus.PENDING_LATE,
                                left_record_id=left_id,
                                right_record_id=_record_id(late_candidate),
                                variance_minor=0,
                                reason_code="AFTER_CUTOFF",
                                left_amount_minor=_amount_minor(left_record),
                                right_amount_minor=_amount_minor(late_candidate),
                                evidence={
                                    "cutoff_at": cutoff_dt.isoformat(),
                                    "candidate_occurred_at": _occurred_at(late_candidate).isoformat(),
                                },
                            )
                        )
                        consumed_left.add(left_id)
                        continue

            best: tuple[float, dict[str, Any]] | None = None
            for candidate in candidate_matches:
                right_id = _record_id(candidate)
                if right_id in consumed_right:
                    continue
                score = self._match_score(left_record, candidate, currency=currency)
                if score > (best[0] if best else -1.0):
                    best = (score, candidate)

            if best is None:
                results.append(
                    ReconciliationMatch(
                        status=ReconciliationStatus.INTERNAL_ONLY,
                        left_record_id=left_id,
                        right_record_id=None,
                        variance_minor=0,
                        reason_code="NO_AVAILABLE_RIGHT",
                        left_amount_minor=_amount_minor(left_record),
                        evidence={"left_reference": _reference(left_record)},
                    )
                )
                consumed_left.add(left_id)
                continue

            match_record = best[1]
            right_id = _record_id(match_record)
            if self._is_ambiguous(left_record, match_record, candidate_matches, consumed_right):
                ambiguous_ids = sorted(
                    {
                        _record_id(item)
                        for item in candidate_matches
                        if _record_id(item) not in consumed_right
                    }
                )
                results.append(
                    ReconciliationMatch(
                        status=ReconciliationStatus.AMBIGUOUS,
                        left_record_id=left_id,
                        right_record_id=None,
                        variance_minor=0,
                        reason_code="MULTIPLE_CANDIDATES",
                        left_amount_minor=_amount_minor(left_record),
                        right_amount_minor=_amount_minor(match_record),
                        evidence={
                            "candidate_ids": ambiguous_ids,
                            "algorithm": self.ALGORITHM_VERSION,
                        },
                    )
                )
                consumed_left.add(left_id)
                continue

            status = self._evaluate_pair(left_record, match_record, currency=currency)
            results.append(
                ReconciliationMatch(
                    status=status,
                    left_record_id=left_id,
                    right_record_id=right_id,
                    variance_minor=self._variance_minor(left_record, match_record),
                    reason_code=self._reason_code(status),
                    left_amount_minor=_amount_minor(left_record),
                    right_amount_minor=_amount_minor(match_record),
                    evidence={
                        "reference": _reference(left_record),
                        "candidate_reference": _reference(match_record),
                        "currency": _currency(left_record),
                        "algorithm": self.ALGORITHM_VERSION,
                        "match_score": self._match_score(left_record, match_record, currency=currency),
                    },
                )
            )
            consumed_left.add(left_id)
            consumed_right.add(right_id)

        for right_record in right:
            right_id = _record_id(right_record)
            if right_id in consumed_right:
                continue
            right_occurred = _occurred_at(right_record)
            if start_dt is not None and right_occurred is not None and right_occurred < start_dt:
                continue
            if cutoff_dt is not None and right_occurred is not None and right_occurred > cutoff_dt:
                results.append(
                    ReconciliationMatch(
                        status=ReconciliationStatus.PENDING_LATE,
                        left_record_id=None,
                        right_record_id=right_id,
                        variance_minor=0,
                        reason_code="AFTER_CUTOFF",
                        right_amount_minor=_amount_minor(right_record),
                        evidence={"cutoff_at": cutoff_dt.isoformat(), "occurred_at": right_occurred.isoformat()},
                    )
                )
                consumed_right.add(right_id)
                continue
            results.append(
                ReconciliationMatch(
                    status=ReconciliationStatus.COUNTERPART_ONLY,
                    left_record_id=None,
                    right_record_id=right_id,
                    variance_minor=0,
                    reason_code="NO_LEFT_MATCH",
                    right_amount_minor=_amount_minor(right_record),
                    evidence={"counterpart_reference": _reference(right_record)},
                )
            )
            consumed_right.add(right_id)

        return results

    def _candidate_records(
        self,
        left_record: dict[str, Any],
        right_by_ref: dict[str, list[dict[str, Any]]],
        right_by_compound: dict[str, list[dict[str, Any]]],
        right_records: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        exact_ref = _normalize_ref(_reference(left_record))
        if exact_ref:
            refs = right_by_ref.get(exact_ref, [])
            if refs:
                return refs

        compound = self._compound_key(left_record)
        if compound:
            compound_matches = right_by_compound.get(compound, [])
            if compound_matches:
                return compound_matches

        candidates: list[dict[str, Any]] = []
        left_ref = _reference(left_record)
        for record in right_records:
            if _normalize_ref(_reference(record)) == exact_ref:
                candidates.append(record)
                continue
            if left_ref and _reference(record):
                left_text = left_ref.lower().strip()
                right_text = _reference(record).lower().strip()
                if left_text and right_text and self._text_similarity(left_text, right_text) >= self.similarity_threshold:
                    candidates.append(record)
        return candidates

    @staticmethod
    def _compound_key(record: dict[str, Any]) -> str:
        ref = _normalize_ref(_reference(record))
        amount = _amount_minor(record)
        source = _source(record) or ""
        currency = _currency(record) or ""
        if not ref and amount is None and not source and not currency:
            return ""
        return f"{ref}|{amount}|{source}|{currency}".lower()

    @staticmethod
    def _text_similarity(a: str, b: str) -> float:
        if a == b:
            return 1.0
        if not a or not b:
            return 0.0
        overlap = sum(1 for ch in set(a) if ch in set(b))
        return overlap / max(len(set(a) | set(b)), 1)

    @staticmethod
    def _variance_minor(left: dict[str, Any], right: dict[str, Any]) -> int:
        left_amount = _amount_minor(left)
        right_amount = _amount_minor(right)
        if left_amount is None or right_amount is None:
            return 0
        return abs(left_amount - right_amount)

    @staticmethod
    def _match_score(left_record: dict[str, Any], right_record: dict[str, Any], *, currency: str | None) -> float:
        left_ref = _normalize_ref(_reference(left_record))
        right_ref = _normalize_ref(_reference(right_record))
        if currency is not None:
            left_currency = _currency(left_record)
            right_currency = _currency(right_record)
            if left_currency and right_currency and left_currency != currency.upper():
                return 0.0
            if right_currency and right_currency != currency.upper():
                return 0.0
        if left_ref and right_ref:
            if left_ref == right_ref:
                return 1.0
            if left_ref in right_ref or right_ref in left_ref:
                return 0.85
        if _amount_minor(left_record) is not None and _amount_minor(right_record) is not None:
            left_amount = _amount_minor(left_record)
            right_amount = _amount_minor(right_record)
            if left_amount == right_amount:
                return 0.75
            if right_amount is not None and left_amount == -right_amount:
                return 0.8
        return 0.0

    @staticmethod
    def _is_ambiguous(
        left_record: dict[str, Any],
        right_record: dict[str, Any],
        candidate_matches: list[dict[str, Any]],
        consumed_right: set[str],
    ) -> bool:
        right_id = _record_id(right_record)
        if right_id in consumed_right:
            return True
        if not candidate_matches:
            return False
        matches = [
            item for item in candidate_matches if _record_id(item) not in consumed_right and _record_id(item) != right_id
        ]
        return len(matches) > 0

    @staticmethod
    def _reason_code(status: ReconciliationStatus) -> str:
        return {
            ReconciliationStatus.MATCHED: "MATCH_EXACT",
            ReconciliationStatus.AMOUNT_MISMATCH: "AMOUNT_MISMATCH",
            ReconciliationStatus.FIELD_MISMATCH: "FIELD_MISMATCH",
            ReconciliationStatus.INTERNAL_ONLY: "INTERNAL_ONLY",
            ReconciliationStatus.COUNTERPART_ONLY: "COUNTERPART_ONLY",
            ReconciliationStatus.PENDING_LATE: "PENDING_LATE",
            ReconciliationStatus.AMBIGUOUS: "AMBIGUOUS",
            ReconciliationStatus.UNBALANCED_JOURNAL: "UNBALANCED_JOURNAL",
        }[status]

    @staticmethod
    def _evaluate_pair(
        left_record: dict[str, Any],
        right_record: dict[str, Any],
        *,
        currency: str | None,
    ) -> ReconciliationStatus:
        left_amount = _amount_minor(left_record)
        right_amount = _amount_minor(right_record)
        left_currency = _currency(left_record)
        right_currency = _currency(right_record)

        if currency is not None:
            if left_currency and right_currency and left_currency != currency.upper():
                return ReconciliationStatus.FIELD_MISMATCH
            if right_currency and right_currency != currency.upper():
                return ReconciliationStatus.FIELD_MISMATCH

        if left_currency and right_currency and left_currency != right_currency:
            return ReconciliationStatus.FIELD_MISMATCH

        if _normalize_ref(_reference(left_record)) and _normalize_ref(_reference(right_record)):
            if _normalize_ref(_reference(left_record)) == _normalize_ref(_reference(right_record)):
                if left_amount is not None and right_amount is not None:
                    if left_amount == right_amount or left_amount == -right_amount:
                        return ReconciliationStatus.MATCHED
                    return ReconciliationStatus.AMOUNT_MISMATCH
                return ReconciliationStatus.FIELD_MISMATCH

        if left_amount is not None and right_amount is not None:
            if left_amount == right_amount or left_amount == -right_amount:
                return ReconciliationStatus.MATCHED
            if abs(left_amount - right_amount) > 0:
                return ReconciliationStatus.AMOUNT_MISMATCH
        return ReconciliationStatus.FIELD_MISMATCH


def compute_run_id(
    *,
    source_left_id: str,
    source_right_id: str,
    start_at: datetime | str,
    cutoff_at: datetime | str,
    currency: str,
    policy_version: str,
    input_checkpoint: str,
) -> str:
    start_dt = _coerce_utc_datetime(start_at)
    cutoff_dt = _coerce_utc_datetime(cutoff_at)
    start_value = start_dt.isoformat() if start_dt is not None else str(start_at)
    cutoff_value = cutoff_dt.isoformat() if cutoff_dt is not None else str(cutoff_at)
    raw = "|".join(
        [
            str(source_left_id),
            str(source_right_id),
            start_value,
            cutoff_value,
            str(currency).upper(),
            str(policy_version),
            str(input_checkpoint),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def match_records(
    left_records: Iterable[dict[str, Any]],
    right_records: Iterable[dict[str, Any]],
    *,
    cutoff_at: datetime | None = None,
    currency: str | None = None,
) -> list[ReconciliationMatch]:
    return ReconciliationMatcher().match_records(left_records, right_records, cutoff_at=cutoff_at, currency=currency)
