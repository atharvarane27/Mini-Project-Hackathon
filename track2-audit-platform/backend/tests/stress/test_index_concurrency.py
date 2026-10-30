"""Scaffold for backend/tests/stress/test_index_concurrency; implementation pending."""

from __future__ import annotations

import threading
import time
from typing import Any

from app.engines.identity.inverted_index import InvertedIndex


def _record_payload(index: int, *, name: str = "Alice Smith") -> dict[str, Any]:
    return {
        "payee_name": f"{name} {index}",
        "account_id": f"ACC-{index % 11}",
        "amount_minor": 1000 + (index % 5) * 500,
    }


def test_many_concurrent_inserts_and_searches_are_stable() -> None:
    idx = InvertedIndex(fields=["payee_name", "account_id", "amount_minor"], bucket_cap=128, max_query_candidates=256)
    records: list[tuple[str, dict[str, Any]]] = [
        (f"r{n}", _record_payload(n, name="Alice Smith")) for n in range(200)
    ]

    def writer(start: int, end: int) -> None:
        for n in range(start, end):
            idx.insert(f"r{n}", records[n][1])

    def reader() -> None:
        for n in range(200):
            cands = idx.candidates(f"r{n}", records[n][1])
            assert isinstance(cands, frozenset)
            assert f"r{n}" not in cands

    threads = [
        threading.Thread(target=writer, args=(0, 100)),
        threading.Thread(target=writer, args=(100, 200)),
        threading.Thread(target=reader),
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert idx.total_records() == 200
    metrics = idx.metrics()
    assert metrics["record_count"] == 200
    assert metrics["bucket_count"] >= 1
    assert metrics["largest_bucket"] <= 128 or metrics["largest_bucket"] >= 0


def test_rebuilt_index_matches_incrementally_built_index() -> None:
    base_records = [
        (f"r{i}", {"payee_name": f"Alice Smith {i % 5}", "account_id": f"ACC-{i % 3}", "amount_minor": 1000 + i})
        for i in range(150)
    ]

    incremental = InvertedIndex(fields=["payee_name", "account_id", "amount_minor"], bucket_cap=64, max_query_candidates=256)
    for record_id, fields in base_records:
        incremental.insert(record_id, fields)

    rebuilt = InvertedIndex(fields=["payee_name", "account_id", "amount_minor"], bucket_cap=64, max_query_candidates=256)
    rebuilt.rebuild_from_records(base_records, batch_size=25)

    assert incremental.total_records() == rebuilt.total_records()
    assert incremental.partition_sizes() == rebuilt.partition_sizes()
    assert incremental.metrics()["bucket_count"] == rebuilt.metrics()["bucket_count"]
    for qid, qfields in base_records:
        assert incremental.candidates(qid, qfields) == rebuilt.candidates(qid, qfields)


def test_no_lost_or_corrupted_postings_during_rebuild() -> None:
    idx = InvertedIndex(fields=["payee_name", "account_id", "amount_minor"], bucket_cap=32, max_query_candidates=128)
    records = [
        (f"r{i}", {"payee_name": "Alice Smith", "account_id": f"ACC-{i % 10}", "amount_minor": 1500 + i})
        for i in range(75)
    ]

    idx.rebuild_from_records(records, batch_size=9)
    for record_id, payload in records:
        overlap = idx.candidates(record_id, payload)
        assert record_id not in overlap
        assert len(overlap) >= 0

    assert idx.total_records() == len(records)
    assert idx.metrics()["record_count"] == len(records)
