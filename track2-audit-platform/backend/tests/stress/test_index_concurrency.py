"""P05 concurrent insert/search integrity test."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from app.engines.identity.blocking import BlockingPolicy
from app.engines.identity.inverted_index import InvertedIndex
from app.engines.identity.resolver import IdentityRecord


NOW = datetime(2026, 10, 30, tzinfo=UTC)


def make_record(number: int) -> IdentityRecord:
    return IdentityRecord(
        f"record-{number}", f"REF-{number % 100}", f"S-{number % 50}",
        f"R-{number % 60}", f"Sender {number % 100}", f"Receiver {number % 100}",
        100_000 + (number % 10) * 1_000, "INR", NOW,
    )


def test_concurrent_inserts_and_searches_preserve_posting_lists() -> None:
    index = InvertedIndex(BlockingPolicy(max_bucket_size=250))
    records = tuple(make_record(number) for number in range(2_000))

    def insert_batch(start: int) -> None:
        for item in records[start : start + 100]:
            index.insert(item)
            index.candidates_for(item)

    with ThreadPoolExecutor(max_workers=20) as executor:
        list(executor.map(insert_batch, range(0, 2_000, 100)))

    snapshot = index.snapshot()
    metrics = index.metrics()
    assert len(snapshot.record_ids) == 2_000
    assert metrics.record_count == 2_000
    assert metrics.insert_count == 2_000
    assert metrics.lookup_count == 2_000
    assert all(len(ids) == len(set(ids)) for ids in snapshot.postings.values())
