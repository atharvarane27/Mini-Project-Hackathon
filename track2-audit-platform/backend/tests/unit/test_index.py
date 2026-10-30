"""P05 blocking-key and inverted-index tests."""

from datetime import UTC, datetime

from app.engines.identity.blocking import BlockingPolicy, blocking_keys
from app.engines.identity.inverted_index import InvertedIndex
from app.engines.identity.resolver import IdentityRecord


NOW = datetime(2026, 10, 30, tzinfo=UTC)


def record(record_id: str, reference: str = "REF-1", sender: str = "A") -> IdentityRecord:
    return IdentityRecord(
        record_id, reference, sender, "B", "Atharva Rane", "Example Supplier",
        125_000, "INR", NOW,
    )


def test_blocking_keys_are_deterministic_and_financially_partitioned() -> None:
    keys = blocking_keys(record("one"), BlockingPolicy(amount_band_minor=100_000))
    assert keys == tuple(sorted(keys))
    assert "ref:ref1" in keys
    assert any(key.startswith("financial:2026-10-30|1|INR") for key in keys)
    assert any(key.startswith("phonetic:") for key in keys)


def test_incremental_insert_lookup_update_and_remove() -> None:
    index = InvertedIndex()
    first, candidate = record("one"), record("two")
    index.insert(first)
    index.insert(candidate)
    assert index.candidates_for(first) == (candidate,)
    updated = record("two", reference="OTHER", sender="X")
    index.insert(updated)
    assert index.candidates_for(first) == (updated,)
    assert "two" not in index.snapshot().postings["ref:ref1"]
    assert index.remove("two") is True
    assert index.remove("two") is False
    assert index.metrics().record_count == 1


def test_rebuild_matches_incremental_snapshot() -> None:
    records = tuple(record(f"record-{index}", reference=f"REF-{index % 4}") for index in range(40))
    incremental = InvertedIndex()
    for item in records:
        incremental.insert(item)
    rebuilt = InvertedIndex()
    rebuilt.rebuild(reversed(records))
    assert rebuilt.snapshot() == incremental.snapshot()


def test_skewed_bucket_is_skipped_and_metrics_expose_it() -> None:
    policy = BlockingPolicy(max_bucket_size=3)
    index = InvertedIndex(policy)
    for number in range(6):
        index.insert(record(f"record-{number}", reference=f"UNIQUE-{number}", sender=f"S-{number}"))
    probe = record("probe", reference="UNIQUE-0", sender="S-0")
    assert tuple(item.record_id for item in index.candidates_for(probe)) == ("record-0",)
    metrics = index.metrics()
    assert metrics.skewed_bucket_skips >= 1
    assert metrics.posting_visits < metrics.record_count * len(blocking_keys(probe))
    assert metrics.estimated_memory_bytes > 0
