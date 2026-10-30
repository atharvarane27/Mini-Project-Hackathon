"""Application-owned, thread-safe blocking-key inverted index."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from threading import RLock
from time import perf_counter_ns
from types import MappingProxyType

from .blocking import BlockingPolicy, blocking_keys
from .resolver import IdentityRecord


@dataclass(frozen=True, slots=True)
class IndexMetrics:
    record_count: int
    key_count: int
    posting_count: int
    insert_count: int
    remove_count: int
    lookup_count: int
    posting_visits: int
    skewed_bucket_skips: int
    estimated_memory_bytes: int
    total_lookup_nanoseconds: int
    maximum_lookup_nanoseconds: int


@dataclass(frozen=True, slots=True)
class IndexSnapshot:
    postings: Mapping[str, tuple[str, ...]]
    record_ids: tuple[str, ...]


class InvertedIndex:
    def __init__(self, policy: BlockingPolicy | None = None) -> None:
        self.policy = policy or BlockingPolicy()
        self._lock = RLock()
        self._postings: dict[str, set[str]] = {}
        self._records: dict[str, IdentityRecord] = {}
        self._record_keys: dict[str, tuple[str, ...]] = {}
        self._insert_count = self._remove_count = self._lookup_count = 0
        self._posting_visits = self._skewed_bucket_skips = 0
        self._total_lookup_ns = self._maximum_lookup_ns = 0

    def insert(self, record: IdentityRecord) -> None:
        keys = blocking_keys(record, self.policy)
        with self._lock:
            existing = self._records.get(record.record_id)
            if existing == record:
                return
            if existing is not None:
                self._remove_unlocked(record.record_id)
            self._records[record.record_id] = record
            self._record_keys[record.record_id] = keys
            for key in keys:
                self._postings.setdefault(key, set()).add(record.record_id)
            self._insert_count += 1

    def _remove_unlocked(self, record_id: str) -> bool:
        keys = self._record_keys.pop(record_id, None)
        if keys is None:
            return False
        del self._records[record_id]
        for key in keys:
            posting = self._postings[key]
            posting.remove(record_id)
            if not posting:
                del self._postings[key]
        self._remove_count += 1
        return True

    def remove(self, record_id: str) -> bool:
        with self._lock:
            return self._remove_unlocked(record_id)

    def rebuild(self, records: Iterable[IdentityRecord]) -> None:
        replacement = InvertedIndex(self.policy)
        for record in records:
            replacement.insert(record)
        with self._lock:
            self._postings = replacement._postings
            self._records = replacement._records
            self._record_keys = replacement._record_keys
            self._insert_count += len(replacement._records)

    def candidates_for(self, record: IdentityRecord) -> tuple[IdentityRecord, ...]:
        started = perf_counter_ns()
        keys = blocking_keys(record, self.policy)
        with self._lock:
            candidate_ids: set[str] = set()
            visits = 0
            skewed = 0
            for key in keys:
                posting = self._postings.get(key, set())
                if len(posting) > self.policy.max_bucket_size:
                    skewed += 1
                    continue
                visits += len(posting)
                candidate_ids.update(posting)
            candidate_ids.discard(record.record_id)
            ordered_ids = sorted(candidate_ids)[: self.policy.max_bucket_size]
            result = tuple(self._records[record_id] for record_id in ordered_ids)
            elapsed = perf_counter_ns() - started
            self._lookup_count += 1
            self._posting_visits += visits
            self._skewed_bucket_skips += skewed
            self._total_lookup_ns += elapsed
            self._maximum_lookup_ns = max(self._maximum_lookup_ns, elapsed)
            return result

    def snapshot(self) -> IndexSnapshot:
        with self._lock:
            postings = {
                key: tuple(sorted(record_ids))
                for key, record_ids in sorted(self._postings.items())
            }
            return IndexSnapshot(
                MappingProxyType(postings), tuple(sorted(self._records))
            )

    def metrics(self) -> IndexMetrics:
        with self._lock:
            posting_count = sum(len(posting) for posting in self._postings.values())
            memory = sum(len(key) for key in self._postings)
            memory += sum(len(record_id) for record_id in self._records)
            memory += posting_count * 16
            return IndexMetrics(
                len(self._records), len(self._postings), posting_count,
                self._insert_count, self._remove_count, self._lookup_count,
                self._posting_visits, self._skewed_bucket_skips, memory,
                self._total_lookup_ns, self._maximum_lookup_ns,
            )
