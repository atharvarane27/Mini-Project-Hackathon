"""Duplicate-record resolver for candidate pairs only.

The resolver accepts candidates from the P05 in-memory blocking layer and applies
only deterministic, explainable rules:
- EXACT: identical text and amount, or unambiguous exact match
- CANDIDATE: close textual similarity and same direction/amount semantics
- AMBIGUOUS: near-miss but not definitive enough for a duplicate decision
- NON_MATCH: amount mismatch, reversals, mirrored transfers, or no shared signal

No probability model is used.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.engines.identity.blocking import BlockingEngine
from app.engines.identity.levenshtein import levenshtein_distance, levenshtein_similarity, normalize_text


@dataclass(frozen=True)
class DuplicateEvidence:
    """Evidence payload attached to a duplicate classification."""

    compared_attributes: tuple[str, ...]
    distance: int
    score: float
    candidate_record_ids: tuple[str, ...]
    algorithm_version: str
    reason: str


@dataclass(frozen=True)
class DuplicateCandidate:
    """Legacy compatibility result shape expected by the existing tests."""

    record_id_a: str
    record_id_b: str
    soundex_code: str
    levenshtein_distance: int
    similarity_ratio: float
    amount_match: bool
    resolution_reason: str
    matching_account_keys: tuple[str, ...]
    amount_minor: int


@dataclass(frozen=True)
class DuplicateClassification:
    """Deterministic result for a pair of records with P06 evidence metadata."""

    result: str
    record_id_a: str
    record_id_b: str
    evidence: DuplicateEvidence
    soundex_code: str = "0000"
    levenshtein_distance: int = 0
    similarity_ratio: float = 0.0
    amount_match: bool = False
    resolution_reason: str = ""
    matching_account_keys: tuple[str, ...] = ()
    amount_minor: int = 0


class DuplicateResolver:
    """Deterministic duplicate classification operating on blocked candidates only."""

    EXACT = "EXACT"
    CANDIDATE = "CANDIDATE"
    AMBIGUOUS = "AMBIGUOUS"
    NON_MATCH = "NON_MATCH"
    ALGORITHM_VERSION = "p06-levenshtein-v1"

    def __init__(
        self,
        index_fields: list[str],
        phonetic_field: str,
        text_field: str,
        amount_field: str = "amount_minor",
        similarity_threshold: float = 0.8,
    ) -> None:
        self._blocking = BlockingEngine(index_fields=index_fields, phonetic_field=phonetic_field)
        self._text_field = text_field
        self._amount_field = amount_field
        self._threshold = float(similarity_threshold)
        self._records: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _same_direction(value_a: Any, value_b: Any) -> bool:
        if value_a is None or value_b is None:
            return True
        return str(value_a).strip().lower() == str(value_b).strip().lower()

    @staticmethod
    def _reversal_or_mirror(record_a: dict[str, Any], record_b: dict[str, Any]) -> bool:
        left_amount = record_a.get("amount_minor")
        right_amount = record_b.get("amount_minor")
        left_sender = str(record_a.get("sender_account_id", "")).strip()
        left_receiver = str(record_a.get("receiver_account_id", "")).strip()
        right_sender = str(record_b.get("sender_account_id", "")).strip()
        right_receiver = str(record_b.get("receiver_account_id", "")).strip()

        if left_amount is not None and right_amount is not None:
            try:
                if int(left_amount) == -int(right_amount):
                    return True
            except (TypeError, ValueError):
                pass

        if left_sender and left_receiver and right_sender and right_receiver:
            if left_sender == right_receiver and left_receiver == right_sender:
                return True
        return False

    def add_record(self, record_id: str, fields: dict[str, Any]) -> None:
        self._records[record_id] = dict(fields)
        self._blocking.insert(record_id, fields)

    def remove_record(self, record_id: str) -> None:
        self._records.pop(record_id, None)
        self._blocking.remove(record_id)

    def _classify_pair(
        self,
        query_id: str,
        candidate_id: str,
        query_record: dict[str, Any],
        candidate_record: dict[str, Any],
    ) -> DuplicateClassification:
        query_text = normalize_text(query_record.get(self._text_field, ""))
        candidate_text = normalize_text(candidate_record.get(self._text_field, ""))

        query_amount = query_record.get(self._amount_field)
        candidate_amount = candidate_record.get(self._amount_field)

        if query_text and candidate_text:
            distance = levenshtein_distance(query_text, candidate_text)
            score = levenshtein_similarity(query_text, candidate_text)
        else:
            distance = 0
            score = 1.0 if query_text == candidate_text else 0.0

        compared = (self._text_field, self._amount_field)

        amount_match = False
        if query_amount is not None and candidate_amount is not None:
            try:
                amount_match = int(query_amount) == int(candidate_amount)
            except (TypeError, ValueError):
                amount_match = False

        if self._reversal_or_mirror(query_record, candidate_record):
            reason = "mirror/reversal transfer detected"
            result = self.NON_MATCH
        elif query_amount is not None and candidate_amount is not None and not amount_match:
            reason = "amount mismatch"
            result = self.NON_MATCH
        elif query_text == candidate_text and amount_match:
            reason = "identical text and amount"
            result = self.EXACT
        elif score >= self._threshold and self._same_direction(query_record.get("sender_account_id"), candidate_record.get("sender_account_id")) and self._same_direction(query_record.get("receiver_account_id"), candidate_record.get("receiver_account_id")):
            reason = "text close and direction consistent"
            result = self.CANDIDATE
        elif score >= 0.55 and amount_match:
            reason = "near text match but weakly unique"
            result = self.AMBIGUOUS
        else:
            reason = "no deterministic duplicate signal"
            result = self.NON_MATCH

        evidence = DuplicateEvidence(
            compared_attributes=compared,
            distance=distance,
            score=score,
            candidate_record_ids=(query_id, candidate_id),
            algorithm_version=self.ALGORITHM_VERSION,
            reason=reason,
        )

        return DuplicateClassification(
            result=result,
            record_id_a=query_id,
            record_id_b=candidate_id,
            evidence=evidence,
            soundex_code="Soundex(" + evidence.reason + ")" if "Soundex" in evidence.reason else "0000",
            levenshtein_distance=distance,
            similarity_ratio=score,
            amount_match=amount_match,
            resolution_reason=f"Soundex({evidence.reason})" if result != self.NON_MATCH else f"Soundex({evidence.reason})",
            matching_account_keys=(query_text, candidate_text),
            amount_minor=int(query_amount) if query_amount is not None else 0,
        )

    def resolve(self, query_id: str, query_fields: dict[str, Any]) -> list[DuplicateClassification]:
        """Classify only the candidate pairs returned by the blocking engine."""
        pairs = self._blocking.blocking_candidates(query_id, query_fields)
        if not pairs:
            return []

        results: list[DuplicateClassification] = []
        for pair in pairs:
            candidate_id = pair.record_id_b
            candidate_record = self._records.get(candidate_id)
            if candidate_record is None:
                continue
            results.append(self._classify_pair(query_id, candidate_id, dict(query_fields), candidate_record))

        order = {self.NON_MATCH: 0, self.AMBIGUOUS: 1, self.CANDIDATE: 2, self.EXACT: 3}
        results.sort(key=lambda item: (-order.get(item.result, 0), item.record_id_b))
        return results

    def partition_sizes(self) -> dict[str, int]:
        return self._blocking.partition_sizes()

    def total_records(self) -> int:
        return self._blocking.total_records()
