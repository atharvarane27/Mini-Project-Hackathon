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

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.engines.identity.inverted_index import InvertedIndex
from app.engines.identity.soundex import soundex


def _tokenise(value: Any) -> set[str]:
    """Tokenise a field for inverted-index overlap checks."""
    if value is None:
        return set()
    text = str(value).lower().strip()
    if not text:
        return set()
    return {tok for tok in text.split() if tok}


def _date_bucket(value: Any) -> str | None:
    """Normalise date-like values into a coarse bucket used for financial recall."""
    if value is None:
        return None
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return raw[:10]
        return dt.date().isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    return str(value)[:10]


def _amount_band(value: Any, bucket_size: int = 10000) -> str | None:
    """Convert an amount into a coarse bucket and its adjacent bands for recall."""
    if value is None:
        return None
    try:
        amount = int(value)
    except (TypeError, ValueError):
        return None
    if amount < 0:
        amount = -amount
    base = (amount // bucket_size) * bucket_size
    return f"{base}-{base + bucket_size - 1}"


def _amount_band_neighbors(value: Any, bucket_size: int = 10000) -> set[str]:
    """Include neighboring amount bands to preserve recall under small amount drift."""
    band = _amount_band(value, bucket_size)
    if band is None:
        return set()
    try:
        start = int(band.split("-")[0])
    except (IndexError, ValueError):
        return {band}
    return {
        f"{start - bucket_size}-{start - 1}",
        f"{start}-{start + bucket_size - 1}",
        f"{start + bucket_size}-{start + (2 * bucket_size) - 1}",
    }


def _financial_blocking_keys(fields: dict[str, Any], bucket_size: int = 10000) -> set[str]:
    """Return a compact set of financial keys used as blocking features."""
    keys: set[str] = set()
    sender = fields.get("sender_account_id")
    if sender is not None:
        keys.add(f"acct:{str(sender).strip()}")
    receiver = fields.get("receiver_account_id")
    if receiver is not None:
        keys.add(f"acct:{str(receiver).strip()}")
    currency = fields.get("currency")
    if currency is not None:
        keys.add(f"currency:{str(currency).strip().upper()}")
    date_bucket = _date_bucket(fields.get("occurred_at") or fields.get("posted_at"))
    if date_bucket is not None:
        keys.add(f"date:{date_bucket}")
    amount_value = fields.get("amount_minor")
    amount_key = _amount_band(amount_value, bucket_size)
    if amount_key is not None:
        keys.add(f"amount:{amount_key}")
        keys.update(f"amount:{band}" for band in _amount_band_neighbors(amount_value, bucket_size))
    return keys


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
        *,
        bucket_size: int = 10000,
    ) -> None:
        self._index = InvertedIndex(fields=index_fields)
        self._phonetic_field = phonetic_field
        self._bucket_size = int(bucket_size)
        # record_id → soundex code for the phonetic field
        self._soundex_cache: dict[str, str] = {}
        self._records: dict[str, dict[str, Any]] = {}

    def insert(self, record_id: str, fields: dict[str, Any]) -> None:
        """Add a record to the blocking index.

        Args:
            record_id: Stable unique identifier.
            fields: Record field values (only relevant fields used).
        """
        self._index.insert(record_id, fields)
        self._records[record_id] = dict(fields)
        phonetic_value = fields.get(self._phonetic_field, "")
        self._soundex_cache[record_id] = soundex(str(phonetic_value))

    def remove(self, record_id: str) -> None:
        """Remove a record from the blocking index."""
        self._index.remove(record_id)
        self._soundex_cache.pop(record_id, None)
        self._records.pop(record_id, None)

    @staticmethod
    def _shared_tokens_for(query_fields: dict[str, Any], candidate_fields: dict[str, Any]) -> frozenset[str]:
        """Compute the common token overlap between two records across indexed fields."""
        shared: set[str] = set()
        for field_name in set(query_fields) | set(candidate_fields):
            query_tokens = _tokenise(query_fields.get(field_name))
            candidate_tokens = _tokenise(candidate_fields.get(field_name))
            if query_tokens and candidate_tokens:
                shared.update(query_tokens & candidate_tokens)
        return frozenset(shared)

    @staticmethod
    def _financial_overlap(query_fields: dict[str, Any], candidate_fields: dict[str, Any], bucket_size: int = 10000) -> bool:
        """Return True when two records share a financial blocking key."""
        left = _financial_blocking_keys(query_fields, bucket_size)
        right = _financial_blocking_keys(candidate_fields, bucket_size)
        return bool(left & right)

    def blocking_candidates(
        self,
        query_id: str,
        query_fields: dict[str, Any],
    ) -> list[BlockingPair]:
        """Return candidate duplicate pairs for *query_id* after both filters.

        Stage 1: Retrieve token-overlap candidates from the inverted index.
        Stage 2: Filter to those sharing the same Soundex code on the phonetic field.
        Stage 3: Require a token overlap or a financial key overlap.
        """
        token_candidates = self._index.candidates(query_id, query_fields)
        if not token_candidates:
            return []

        query_soundex = soundex(str(query_fields.get(self._phonetic_field, "")))
        pairs: list[BlockingPair] = []

        for candidate_id in sorted(token_candidates):
            candidate_fields = self._records.get(candidate_id, {})
            if not candidate_fields:
                continue

            shared_tokens = self._shared_tokens_for(query_fields, candidate_fields)
            financial_overlap = self._financial_overlap(query_fields, candidate_fields, self._bucket_size)
            same_amount = False
            left_amount_raw = query_fields.get("amount_minor")
            right_amount_raw = candidate_fields.get("amount_minor")
            try:
                if left_amount_raw is not None and right_amount_raw is not None:
                    left_amount = int(left_amount_raw)
                    right_amount = int(right_amount_raw)
                    same_amount = left_amount == right_amount
            except (TypeError, ValueError):
                same_amount = False

            if not shared_tokens and not financial_overlap and not (same_amount and self._soundex_cache.get(candidate_id) == query_soundex):
                continue

            if self._soundex_cache.get(candidate_id) != query_soundex:
                continue
            pairs.append(
                BlockingPair(
                    record_id_a=query_id,
                    record_id_b=candidate_id,
                    shared_soundex=query_soundex,
                    shared_tokens=shared_tokens,
                )
            )
        return pairs

    def partition_sizes(self) -> dict[str, int]:
        """Delegate to InvertedIndex.partition_sizes() for metrics reporting."""
        return self._index.partition_sizes()

    def total_records(self) -> int:
        """Return the number of records in the blocking index."""
        return self._index.total_records()

    def metrics(self) -> dict[str, Any]:
        """Return aggregate metrics for the blocking engine."""
        return {
            **self._index.metrics(),
            "record_count": self.total_records(),
            "phonetic_cache_size": len(self._soundex_cache),
            "bucket_size": self._bucket_size,
        }
