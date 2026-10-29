"""Hand-written inverted index for field-level blocking in duplicate detection.

The index maps (field_name, token) → frozenset of record IDs.
Tokens are produced by lowercasing and whitespace-splitting the field value.
Numeric strings are kept as-is (amounts, account numbers).

Complexity:
  - insert: O(t) where t = number of tokens in the record
  - candidates(record): O(t · k) where k = average candidates per token
  - The index avoids all-pairs O(n²) scan; partitioned by field for efficiency.

No external libraries — pure Python only.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def _tokenise(value: Any) -> list[str]:
    """Convert a field value to a list of index tokens.

    - Converts to string, lowercases.
    - Splits on whitespace.
    - Ignores empty tokens.
    - Numeric-looking tokens (amounts, account refs) are kept intact.
    """
    text = str(value).lower().strip()
    return [tok for tok in text.split() if tok]


class InvertedIndex:
    """Field-level inverted index for blocking-based duplicate candidate retrieval.

    Usage::

        idx = InvertedIndex(fields=["payee_name", "amount_minor", "account_id"])
        idx.insert("rec-1", {"payee_name": "JOHN DOE", "amount_minor": 50000, ...})
        idx.insert("rec-2", {"payee_name": "Jon Doe",  "amount_minor": 50000, ...})
        candidates = idx.candidates("rec-1", {"payee_name": "JOHN DOE", ...})
        # candidates → {"rec-2"}

    The index only returns records that share *at least one* token in *any*
    indexed field with the query record, excluding the query record itself.
    """

    def __init__(self, fields: list[str]) -> None:
        """Initialise the index for the given list of field names to index.

        Args:
            fields: Field names that will be tokenised and indexed.
        """
        self._fields = list(fields)
        # _index[(field, token)] → set of record_ids
        self._index: dict[tuple[str, str], set[str]] = defaultdict(set)
        # _records[record_id] → stored field values for retrieval
        self._records: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def insert(self, record_id: str, fields: dict[str, Any]) -> None:
        """Index *record_id* by the tokens in its *fields* dict.

        Args:
            record_id: Stable, unique identifier of the source record.
            fields: Mapping of field_name → value (only indexed fields are used).
        """
        self._records[record_id] = fields
        for field in self._fields:
            value = fields.get(field)
            if value is None:
                continue
            for token in _tokenise(value):
                self._index[(field, token)].add(record_id)

    def remove(self, record_id: str) -> None:
        """Remove a record from the index (e.g. after resolution).

        Args:
            record_id: The record to remove.
        """
        fields = self._records.pop(record_id, {})
        for field in self._fields:
            value = fields.get(field)
            if value is None:
                continue
            for token in _tokenise(value):
                bucket = self._index.get((field, token))
                if bucket is not None:
                    bucket.discard(record_id)
                    if not bucket:
                        del self._index[(field, token)]

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def candidates(
        self,
        query_id: str,
        query_fields: dict[str, Any],
    ) -> frozenset[str]:
        """Return the set of candidate record IDs that share at least one token
        in any indexed field with *query_fields*, excluding *query_id* itself.

        Args:
            query_id: The query record's own ID (excluded from results).
            query_fields: Field values to generate blocking tokens from.

        Returns:
            A frozenset of candidate record IDs.
        """
        result: set[str] = set()
        for field in self._fields:
            value = query_fields.get(field)
            if value is None:
                continue
            for token in _tokenise(value):
                bucket = self._index.get((field, token))
                if bucket:
                    result.update(bucket)
        result.discard(query_id)
        return frozenset(result)

    def partition_sizes(self) -> dict[str, int]:
        """Return the number of index entries per field (for benchmark/metrics).

        Returns:
            Mapping of field_name → number of unique tokens indexed for that field.
        """
        counts: dict[str, int] = {f: 0 for f in self._fields}
        for (field, _token), _ in self._index.items():
            if field in counts:
                counts[field] += 1
        return counts

    def total_records(self) -> int:
        """Return the number of records currently stored in the index."""
        return len(self._records)

    def __len__(self) -> int:
        return len(self._records)
