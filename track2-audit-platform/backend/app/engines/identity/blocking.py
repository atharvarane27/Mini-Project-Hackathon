"""Blocking strategy: combines Soundex phonetic keys with inverted-index
token overlap to produce compact candidate pairs for Levenshtein scoring.

A pair (A, B) is admitted to the candidate set only if:
  1. At least one indexed field shares a token (inverted-index block), AND
  2. The primary text field's Soundex codes match.

This two-stage filter dramatically reduces the comparison space before
the more expensive Levenshtein pass.

No external libraries — pure Python only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.engines.identity.inverted_index import InvertedIndex
from app.engines.identity.soundex import soundex


@dataclass(frozen=True)
class BlockingPair:
    """A candidate duplicate pair produced by the blocking stage.

    Attributes:
        record_id_a: First record's stable ID.
        record_id_b: Second record's stable ID.
        shared_soundex: Soundex code that matched for the phonetic field.
        shared_tokens: Tokens that were shared across indexed fields.
    """

    record_id_a: str
    record_id_b: str
    shared_soundex: str
    shared_tokens: frozenset[str] = field(default_factory=frozenset)

    def pair_key(self) -> frozenset[str]:
        """Canonical unordered pair key for deduplication."""
        return frozenset({self.record_id_a, self.record_id_b})


class BlockingEngine:
    """Two-stage blocking engine: token overlap → Soundex phonetic filter.

    Args:
        index_fields: Fields passed to the underlying InvertedIndex.
        phonetic_field: The field whose value is Soundex-encoded for the
                        second-stage phonetic filter. Must also appear in
                        index_fields or be present in record dicts.
    """

    def __init__(
        self,
        index_fields: list[str],
        phonetic_field: str,
    ) -> None:
        self._index = InvertedIndex(fields=index_fields)
        self._phonetic_field = phonetic_field
        # record_id → soundex code for the phonetic field
        self._soundex_cache: dict[str, str] = {}

    def insert(self, record_id: str, fields: dict[str, Any]) -> None:
        """Add a record to the blocking index.

        Args:
            record_id: Stable unique identifier.
            fields: Record field values (only relevant fields used).
        """
        self._index.insert(record_id, fields)
        phonetic_value = fields.get(self._phonetic_field, "")
        self._soundex_cache[record_id] = soundex(str(phonetic_value))

    def remove(self, record_id: str) -> None:
        """Remove a record from the blocking index."""
        self._index.remove(record_id)
        self._soundex_cache.pop(record_id, None)

    def blocking_candidates(
        self,
        query_id: str,
        query_fields: dict[str, Any],
    ) -> list[BlockingPair]:
        """Return candidate duplicate pairs for *query_id* after both filters.

        Stage 1: Retrieve token-overlap candidates from the inverted index.
        Stage 2: Filter to those sharing the same Soundex code on the phonetic field.

        Args:
            query_id: The query record's stable ID.
            query_fields: The query record's field values.

        Returns:
            List of BlockingPair objects — each represents a candidate pair
            that passed both filters. Empty list if no candidates qualify.
        """
        token_candidates = self._index.candidates(query_id, query_fields)
        if not token_candidates:
            return []

        query_soundex = soundex(str(query_fields.get(self._phonetic_field, "")))
        pairs: list[BlockingPair] = []

        for candidate_id in sorted(token_candidates):  # sorted for determinism
            if self._soundex_cache.get(candidate_id) != query_soundex:
                continue
            pairs.append(
                BlockingPair(
                    record_id_a=query_id,
                    record_id_b=candidate_id,
                    shared_soundex=query_soundex,
                )
            )
        return pairs

    def partition_sizes(self) -> dict[str, int]:
        """Delegate to InvertedIndex.partition_sizes() for metrics reporting."""
        return self._index.partition_sizes()

    def total_records(self) -> int:
        """Return the number of records in the blocking index."""
        return self._index.total_records()
