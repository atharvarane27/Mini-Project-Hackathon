"""Hand-written inverted index for field-level blocking in duplicate detection.

The index maps (field_name, token) → frozenset of record IDs.
Tokens are produced by lowercasing and whitespace-splitting the field value.
Numeric strings are kept as-is (amounts, account numbers).

Complexity:
  - insert: O(t) where t = number of tokens in the record
  - candidates(record): O(t · k) where k = average candidates per token, capped by
    the configured bucket cap and query limit to prevent skewed tokens from
    returning near-all records.
  - The index avoids all-pairs O(n²) scan; partitioned by field for efficiency.

This implementation is intentionally bounded and auditable: in pathological
skew cases, a single hot token may still dominate a partition, but the caller
never gets an unbounded set proportional to the whole dataset.
"""

from __future__ import annotations

import threading
import time
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

    def __init__(
        self,
        fields: list[str],
        *,
        bucket_cap: int = 256,
        max_query_candidates: int = 2048,
    ) -> None:
        """Initialise the index for the given list of field names to index.

        Args:
            fields: Field names that will be tokenised and indexed.
            bucket_cap: Maximum posting-list size exposed for a single token.
            max_query_candidates: Cap on how many candidates a single query may
                receive from the union of all matching buckets.
        """
        if bucket_cap <= 0:
            raise ValueError("bucket_cap must be positive")
        self._fields = list(fields)
        self._bucket_cap = int(bucket_cap)
        self._max_query_candidates = int(max_query_candidates)
        self._index: dict[tuple[str, str], set[str]] = defaultdict(set)
        self._records: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._field_locks = {field: threading.RLock() for field in self._fields}
        self._skew_metrics: dict[tuple[str, str], int] = {}
        self._candidate_lookups = 0
        self._total_candidates_retrieved = 0
        self._last_latency_ms = 0.0

    def _index_record_locked(self, record_id: str, fields: dict[str, Any]) -> None:
        self._records[record_id] = dict(fields)
        for field in self._fields:
            value = fields.get(field)
            if value is None:
                continue
            field_lock = self._field_locks.get(field)
            if field_lock is not None:
                with field_lock:
                    for token in _tokenise(value):
                        bucket = self._index[(field, token)]
                        bucket.add(record_id)
                        self._skew_metrics[(field, token)] = len(bucket)

    def _remove_record_locked(self, record_id: str) -> None:
        fields = self._records.pop(record_id, {})
        for field in self._fields:
            value = fields.get(field)
            if value is None:
                continue
            field_lock = self._field_locks.get(field)
            if field_lock is not None:
                with field_lock:
                    for token in _tokenise(value):
                        bucket = self._index.get((field, token))
                        if bucket is None:
                            continue
                        bucket.discard(record_id)
                        if bucket:
                            self._skew_metrics[(field, token)] = len(bucket)
                        else:
                            del self._index[(field, token)]
                            self._skew_metrics.pop((field, token), None)

    def record_tokens(self, record_id: str) -> frozenset[str]:
        """Return the token set for a stored record, across all indexed fields."""
        with self._lock:
            fields = self._records.get(record_id, {})
            tokens: set[str] = set()
            for field in self._fields:
                value = fields.get(field)
                if value is None:
                    continue
                tokens.update(_tokenise(value))
            return frozenset(tokens)

    def insert(self, record_id: str, fields: dict[str, Any]) -> None:
        """Index *record_id* by the tokens in its *fields* dict."""
        with self._lock:
            self._index_record_locked(record_id, fields)

    def remove(self, record_id: str) -> None:
        """Remove a record from the index (e.g. after resolution)."""
        with self._lock:
            self._remove_record_locked(record_id)

    def rebuild_from_records(
        self,
        records: Any,
        *,
        batch_size: int = 1000,
    ) -> dict[str, Any]:
        """Rebuild the index from an iterable of (record_id, fields) pairs.

        Records are processed in bounded batches so large corpora do not create a
        long-lived in-memory spike while the structure is rebuilt.
        """
        if batch_size <= 0:
            raise ValueError("batch_size must be positive")

        start = time.perf_counter()
        with self._lock:
            self._index.clear()
            self._records.clear()
            self._skew_metrics.clear()
            batch: list[tuple[str, dict[str, Any]]] = []
            total = 0
            for record_id, fields in records:
                batch.append((record_id, dict(fields)))
                if len(batch) >= batch_size:
                    for rid, item_fields in batch:
                        self._index_record_locked(rid, item_fields)
                    total += len(batch)
                    batch.clear()
            if batch:
                for rid, item_fields in batch:
                    self._index_record_locked(rid, item_fields)
                total += len(batch)
        latency_ms = (time.perf_counter() - start) * 1000.0
        metrics = self.metrics()
        metrics["rebuild_latency_ms"] = latency_ms
        metrics["record_count"] = total or self.total_records()
        return metrics

    def candidates(
        self,
        query_id: str,
        query_fields: dict[str, Any],
    ) -> frozenset[str]:
        """Return the set of candidate record IDs capped by bucket and query size.

        A hot token can still be large, but users never receive a near-all corpus
        result from a single token bucket. Candidate sets are bounded per token and
        globally across the query.
        """
        start = time.perf_counter()
        with self._lock:
            result: set[str] = set()
            for field in self._fields:
                value = query_fields.get(field)
                if value is None:
                    continue
                for token in _tokenise(value):
                    bucket = self._index.get((field, token), set())
                    if not bucket:
                        continue
                    capped_bucket = sorted(bucket)[: self._bucket_cap]
                    result.update(capped_bucket)
                    if len(result) >= self._max_query_candidates:
                        result = set(sorted(result)[: self._max_query_candidates])
                        break
                if len(result) >= self._max_query_candidates:
                    result = set(sorted(result)[: self._max_query_candidates])
                    break
            result.discard(query_id)
            self._candidate_lookups += 1
            self._total_candidates_retrieved += len(result)
            self._last_latency_ms = (time.perf_counter() - start) * 1000.0
            return frozenset(result)

    def partition_sizes(self) -> dict[str, int]:
        """Return the number of index entries per field (for benchmark/metrics)."""
        with self._lock:
            counts: dict[str, int] = {f: 0 for f in self._fields}
            for (field, _token), _ in self._index.items():
                if field in counts:
                    counts[field] += 1
            return counts

    def total_records(self) -> int:
        """Return the number of records currently stored in the index."""
        with self._lock:
            return len(self._records)

    def metrics(self) -> dict[str, Any]:
        """Return aggregate metrics for the current index shape."""
        with self._lock:
            bucket_count = len(self._index)
            largest_bucket = max((len(bucket) for bucket in self._index.values()), default=0)
            estimated_memory = (
                len(self._records) * 512
                + bucket_count * 128
                + sum(len(bucket) * 16 for bucket in self._index.values())
            )
            return {
                "record_count": len(self._records),
                "bucket_count": bucket_count,
                "largest_bucket": largest_bucket,
                "memory_estimate_bytes": estimated_memory,
                "candidates_retrieved": self._total_candidates_retrieved,
                "candidate_lookups": self._candidate_lookups,
                "last_latency_ms": self._last_latency_ms,
                "bucket_cap": self._bucket_cap,
                "max_query_candidates": self._max_query_candidates,
            }

    def __len__(self) -> int:
        return self.total_records()
