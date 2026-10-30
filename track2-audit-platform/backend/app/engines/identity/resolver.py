"""Deterministic duplicate classification over pre-blocked candidates."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from threading import Lock
from typing import Protocol

from .levenshtein import bounded_levenshtein, normalize_identity_text


ALGORITHM_VERSION = "identity-resolver-v1"


class DuplicateClassification(StrEnum):
    EXACT = "EXACT"
    CANDIDATE = "CANDIDATE"
    AMBIGUOUS = "AMBIGUOUS"
    NON_MATCH = "NON_MATCH"


class CandidateBucketOverflow(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class IdentityRecord:
    record_id: str
    transaction_reference: str
    sender_account_id: str
    receiver_account_id: str
    sender_name: str
    receiver_name: str
    amount_minor: int
    currency: str
    occurred_at: datetime
    reversal_of_record_id: str | None = None

    def __post_init__(self) -> None:
        required = (
            self.record_id,
            self.transaction_reference,
            self.sender_account_id,
            self.receiver_account_id,
            self.sender_name,
            self.receiver_name,
            self.currency,
        )
        if not all(value.strip() for value in required):
            raise ValueError("identity record fields must not be empty")
        if isinstance(self.amount_minor, bool) or not isinstance(self.amount_minor, int):
            raise TypeError("amount_minor must be an integer")
        if self.amount_minor <= 0:
            raise ValueError("amount_minor must be positive")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        object.__setattr__(self, "currency", self.currency.strip().upper())
        object.__setattr__(self, "occurred_at", self.occurred_at.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class MatchPolicy:
    max_reference_distance: int = 2
    max_name_distance: int = 2
    max_time_delta_minutes: int = 5
    candidate_score_threshold: int = 75
    max_candidates_per_record: int = 500

    def __post_init__(self) -> None:
        if (
            self.max_reference_distance < 0
            or self.max_name_distance < 0
            or self.max_time_delta_minutes < 0
            or not 0 <= self.candidate_score_threshold <= 100
            or self.max_candidates_per_record <= 0
        ):
            raise ValueError("match policy bounds are invalid")


@dataclass(frozen=True, slots=True)
class DuplicateEvidence:
    left_record_id: str
    right_record_id: str
    classification: DuplicateClassification
    score: int
    compared_attributes: Mapping[str, object]
    reasons: tuple[str, ...]
    algorithm_version: str = ALGORITHM_VERSION

    def as_dict(self) -> dict[str, object]:
        return {
            "left_record_id": self.left_record_id,
            "right_record_id": self.right_record_id,
            "classification": self.classification.value,
            "score": self.score,
            "compared_attributes": dict(self.compared_attributes),
            "reasons": list(self.reasons),
            "algorithm_version": self.algorithm_version,
        }


class CandidateProvider(Protocol):
    def candidates_for(self, record: IdentityRecord) -> Iterable[IdentityRecord]: ...


class DuplicateRepository(Protocol):
    def save(self, evidence: Iterable[DuplicateEvidence]) -> tuple[DuplicateEvidence, ...]: ...

    def list(
        self,
        *,
        classification: DuplicateClassification | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[DuplicateEvidence, ...]: ...


def _distance(left: str, right: str, maximum: int) -> int | None:
    return bounded_levenshtein(left, right, maximum)


def _pair_key(left: str, right: str) -> tuple[str, str]:
    return (left, right) if left < right else (right, left)


def compare_records(
    left: IdentityRecord,
    right: IdentityRecord,
    policy: MatchPolicy | None = None,
) -> DuplicateEvidence:
    configured = policy or MatchPolicy()
    if left.record_id == right.record_id:
        raise ValueError("cannot compare a record with itself")
    reversed_pair = (
        left.reversal_of_record_id == right.record_id
        or right.reversal_of_record_id == left.record_id
    )
    inverted = (
        left.sender_account_id == right.receiver_account_id
        and left.receiver_account_id == right.sender_account_id
    )
    same_direction = (
        left.sender_account_id == right.sender_account_id
        and left.receiver_account_id == right.receiver_account_id
    )
    same_money = left.amount_minor == right.amount_minor and left.currency == right.currency
    reference_distance = _distance(
        left.transaction_reference,
        right.transaction_reference,
        configured.max_reference_distance,
    )
    sender_distance = _distance(
        left.sender_name, right.sender_name, configured.max_name_distance
    )
    receiver_distance = _distance(
        left.receiver_name, right.receiver_name, configured.max_name_distance
    )
    time_delta = abs(left.occurred_at - right.occurred_at)
    within_time = time_delta <= timedelta(minutes=configured.max_time_delta_minutes)
    compared = {
        "transaction_reference_distance": reference_distance,
        "sender_name_distance": sender_distance,
        "receiver_name_distance": receiver_distance,
        "same_direction": same_direction,
        "inverted_sides": inverted,
        "same_amount_minor": left.amount_minor == right.amount_minor,
        "same_currency": left.currency == right.currency,
        "time_delta_seconds": int(time_delta.total_seconds()),
        "reversal_pair": reversed_pair,
    }
    if reversed_pair:
        return DuplicateEvidence(
            left.record_id, right.record_id, DuplicateClassification.NON_MATCH,
            0, compared, ("REVERSAL_PAIR",),
        )
    if inverted:
        return DuplicateEvidence(
            left.record_id, right.record_id, DuplicateClassification.NON_MATCH,
            0, compared, ("TRANSFER_SIDES_INVERTED",),
        )
    if not same_money or not same_direction or not within_time:
        return DuplicateEvidence(
            left.record_id, right.record_id, DuplicateClassification.NON_MATCH,
            0, compared, ("FINANCIAL_OR_DIRECTION_MISMATCH",),
        )

    reference_exact = normalize_identity_text(left.transaction_reference) == normalize_identity_text(
        right.transaction_reference
    )
    names_exact = (
        normalize_identity_text(left.sender_name) == normalize_identity_text(right.sender_name)
        and normalize_identity_text(left.receiver_name)
        == normalize_identity_text(right.receiver_name)
    )
    if reference_exact and names_exact:
        return DuplicateEvidence(
            left.record_id, right.record_id, DuplicateClassification.EXACT,
            100, compared, ("EXACT_REFERENCE_PARTIES_AND_MONEY",),
        )
    score = 40
    reasons = ["SAME_DIRECTION_AND_MONEY"]
    if reference_distance is not None:
        score += 30 - 5 * reference_distance
        reasons.append("REFERENCE_WITHIN_EDIT_BOUND")
    if sender_distance is not None and receiver_distance is not None:
        score += 20 - 2 * (sender_distance + receiver_distance)
        reasons.append("PARTY_NAMES_WITHIN_EDIT_BOUND")
    score += 10
    classification = (
        DuplicateClassification.CANDIDATE
        if reference_distance is not None and score >= configured.candidate_score_threshold
        else DuplicateClassification.NON_MATCH
    )
    if classification is DuplicateClassification.NON_MATCH:
        reasons.append("DISTINCT_RECURRING_TRANSACTION_GUARD")
    return DuplicateEvidence(
        left.record_id, right.record_id, classification, score, compared, tuple(reasons)
    )


def resolve_record(
    record: IdentityRecord,
    candidates: Iterable[IdentityRecord],
    policy: MatchPolicy | None = None,
) -> tuple[DuplicateEvidence, ...]:
    configured = policy or MatchPolicy()
    candidate_list = list(candidates)
    if len(candidate_list) > configured.max_candidates_per_record:
        raise CandidateBucketOverflow("candidate bucket exceeds configured bound")
    comparisons = [
        compare_records(record, candidate, configured)
        for candidate in candidate_list
        if candidate.record_id != record.record_id
    ]
    eligible = [
        item
        for item in comparisons
        if item.classification in {
            DuplicateClassification.EXACT,
            DuplicateClassification.CANDIDATE,
        }
    ]
    if len(eligible) > 1:
        best = max(item.score for item in eligible)
        tied_ids = {
            item.right_record_id for item in eligible if item.score == best
        }
        if len(tied_ids) > 1:
            comparisons = [
                replace(item, classification=DuplicateClassification.AMBIGUOUS)
                if item.right_record_id in tied_ids
                else item
                for item in comparisons
            ]
    return tuple(sorted(comparisons, key=lambda item: item.right_record_id))


def analyze_duplicates(
    records: Iterable[IdentityRecord],
    provider: CandidateProvider,
    repository: DuplicateRepository,
    policy: MatchPolicy | None = None,
) -> tuple[DuplicateEvidence, ...]:
    seen_pairs: set[tuple[str, str]] = set()
    evidence: list[DuplicateEvidence] = []
    for record in records:
        for item in resolve_record(record, provider.candidates_for(record), policy):
            pair = _pair_key(item.left_record_id, item.right_record_id)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            evidence.append(item)
    return repository.save(evidence)


class InMemoryDuplicateRepository:
    def __init__(self) -> None:
        self._lock = Lock()
        self._items: dict[tuple[str, str], DuplicateEvidence] = {}

    def save(self, evidence: Iterable[DuplicateEvidence]) -> tuple[DuplicateEvidence, ...]:
        with self._lock:
            for item in evidence:
                key = _pair_key(item.left_record_id, item.right_record_id)
                self._items.setdefault(key, item)
            return tuple(self._items[key] for key in sorted(self._items))

    def list(
        self,
        *,
        classification: DuplicateClassification | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[DuplicateEvidence, ...]:
        if offset < 0 or not 1 <= limit <= 500:
            raise ValueError("invalid duplicate page")
        with self._lock:
            items = [self._items[key] for key in sorted(self._items)]
            if classification is not None:
                items = [item for item in items if item.classification is classification]
            return tuple(items[offset : offset + limit])
