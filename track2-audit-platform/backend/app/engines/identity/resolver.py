"""Duplicate-record resolver: combines blocking candidates with Levenshtein
scoring to produce ranked duplicate findings.

Resolution pipeline:
  1. BlockingEngine.blocking_candidates() → coarse candidate pairs
  2. Levenshtein similarity on the primary text field → score
  3. Amount equality check (exact integer comparison in minor units)
  4. Pairs above *similarity_threshold* are emitted as DuplicateCandidate findings

No external libraries — pure Python only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.engines.identity.blocking import BlockingEngine
from app.engines.identity.levenshtein import levenshtein_distance, levenshtein_similarity


# ---------------------------------------------------------------------------
# Resolution result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DuplicateCandidate:
    """A scored duplicate candidate pair ready to be emitted as a Finding.

    Attributes:
        record_id_a: First record's stable ID.
        record_id_b: Second record's stable ID.
        soundex_code: Shared Soundex code for the phonetic field.
        levenshtein_distance: Raw edit distance on the primary text field.
        similarity_ratio: Normalised [0.0, 1.0] Levenshtein similarity.
        amount_match: True if both records have the same amount_minor value.
        resolution_reason: Human-readable explanation of the match basis.
        matching_account_keys: Field values that formed the blocking key.
        amount_minor: The amount value used in the comparison (from record_a).
    """

    record_id_a: str
    record_id_b: str
    soundex_code: str
    levenshtein_distance: int
    similarity_ratio: float
    amount_match: bool
    resolution_reason: str
    matching_account_keys: tuple[str, ...]
    amount_minor: int


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


class DuplicateResolver:
    """End-to-end duplicate resolution engine.

    Args:
        index_fields: Fields to tokenise in the InvertedIndex.
        phonetic_field: Field Soundex-encoded for phonetic blocking
                        (typically payee/account name).
        text_field: Field for Levenshtein similarity scoring
                    (typically payee name or narration).
        amount_field: Numeric field for exact-amount equality check.
        similarity_threshold: Minimum normalised Levenshtein similarity
                              [0.0, 1.0] for a pair to be emitted.
                              Default 0.7 (70% similarity).
    """

    def __init__(
        self,
        index_fields: list[str],
        phonetic_field: str,
        text_field: str,
        amount_field: str = "amount_minor",
        similarity_threshold: float = 0.7,
    ) -> None:
        self._blocking = BlockingEngine(
            index_fields=index_fields,
            phonetic_field=phonetic_field,
        )
        self._text_field = text_field
        self._amount_field = amount_field
        self._threshold = similarity_threshold
        # Store field values for Levenshtein / amount access
        self._field_store: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def add_record(self, record_id: str, fields: dict[str, Any]) -> None:
        """Add a source record to the resolver's index.

        Args:
            record_id: Stable unique identifier.
            fields: Field values dict (only relevant fields are used).
        """
        self._blocking.insert(record_id, fields)
        self._field_store[record_id] = fields

    def remove_record(self, record_id: str) -> None:
        """Remove a record from the resolver (after resolution/rejection).

        Args:
            record_id: The record to remove.
        """
        self._blocking.remove(record_id)
        self._field_store.pop(record_id, None)

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve(
        self,
        query_id: str,
        query_fields: dict[str, Any],
    ) -> list[DuplicateCandidate]:
        """Run the full resolution pipeline for *query_id*.

        1. Two-stage blocking to get coarse candidate pairs.
        2. Levenshtein scoring on text_field.
        3. Exact amount equality check.
        4. Filter by similarity_threshold.
        5. Return sorted by similarity_ratio descending.

        Args:
            query_id: The query record's stable ID.
            query_fields: The query record's field values.

        Returns:
            List of DuplicateCandidate, sorted best-match first.
            Empty list if no candidates qualify.
        """
        blocking_pairs = self._blocking.blocking_candidates(query_id, query_fields)
        if not blocking_pairs:
            return []

        query_text = str(query_fields.get(self._text_field, ""))
        query_amount = query_fields.get(self._amount_field)

        results: list[DuplicateCandidate] = []

        for pair in blocking_pairs:
            candidate_id = pair.record_id_b
            candidate_fields = self._field_store.get(candidate_id, {})

            candidate_text = str(candidate_fields.get(self._text_field, ""))
            candidate_amount = candidate_fields.get(self._amount_field)

            dist = levenshtein_distance(query_text.lower(), candidate_text.lower())
            ratio = levenshtein_similarity(query_text.lower(), candidate_text.lower())

            if ratio < self._threshold:
                continue

            amount_match = (
                query_amount is not None
                and candidate_amount is not None
                and int(query_amount) == int(candidate_amount)
            )

            reasons: list[str] = [f"Soundex({pair.shared_soundex})"]
            if amount_match:
                reasons.append(f"amount_exact={query_amount}")
            reasons.append(f"lev_sim={ratio:.3f}")

            results.append(
                DuplicateCandidate(
                    record_id_a=query_id,
                    record_id_b=candidate_id,
                    soundex_code=pair.shared_soundex,
                    levenshtein_distance=dist,
                    similarity_ratio=ratio,
                    amount_match=amount_match,
                    resolution_reason="; ".join(reasons),
                    matching_account_keys=(query_text, candidate_text),
                    amount_minor=int(query_amount) if query_amount is not None else 0,
                )
            )

        # Sort best match first
        results.sort(key=lambda c: c.similarity_ratio, reverse=True)
        return results

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def partition_sizes(self) -> dict[str, int]:
        """Return per-field partition sizes for benchmark/observability."""
        return self._blocking.partition_sizes()

    def total_records(self) -> int:
        """Return the number of records indexed."""
        return self._blocking.total_records()
