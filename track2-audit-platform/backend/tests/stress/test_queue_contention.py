"""P15 producer/consumer and priority-update contention tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from app.engines.queue.synchronized_queue import QueueShutdown, SynchronizedCaseQueue


def test_50_producer_consumer_threads_have_no_lost_or_duplicate_cases() -> None:
    queue = SynchronizedCaseQueue()
    producer_count = 25
    consumer_count = 25
    cases_per_producer = 200
    consumed: list[str] = []
    consumed_lock = Lock()

    def produce(producer: int) -> None:
        for item in range(cases_per_producer):
            number = producer * cases_per_producer + item
            queue.put(f"case-{number:05d}", number % 101, 1)

    def consume() -> None:
        local: list[str] = []
        while True:
            try:
                local.append(queue.get().case_id)
            except QueueShutdown:
                break
        with consumed_lock:
            consumed.extend(local)

    with ThreadPoolExecutor(max_workers=producer_count + consumer_count) as executor:
        consumers = [executor.submit(consume) for _ in range(consumer_count)]
        producers = [executor.submit(produce, index) for index in range(producer_count)]
        for future in producers:
            future.result(timeout=20)
        queue.shutdown()
        for future in consumers:
            future.result(timeout=20)

    expected_count = producer_count * cases_per_producer
    assert len(consumed) == expected_count
    assert len(set(consumed)) == expected_count
    assert queue.empty()
    assert queue.validate_heap()
    metrics = queue.metrics()
    assert metrics.push_count == expected_count
    assert metrics.pop_count == expected_count
    assert metrics.condition_wait_count > 0
    assert metrics.shutdown is True


def test_concurrent_versioned_priority_updates_preserve_invariants() -> None:
    queue = SynchronizedCaseQueue()
    case_count = 1_000
    worker_count = 20
    for index in range(case_count):
        queue.put(f"case-{index:04d}", 0, 1)

    def update(worker: int) -> None:
        for index in range(worker, case_count, worker_count):
            queue.update_priority(f"case-{index:04d}", index % 100, 2)

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(update, worker) for worker in range(worker_count)]
        for future in futures:
            future.result(timeout=10)

    assert queue.qsize() == case_count
    assert queue.validate_heap()
    popped = [queue.get() for _ in range(case_count)]
    expected = sorted(
        popped,
        key=lambda item: (-item.priority, item.enqueue_sequence, item.case_id),
    )
    assert popped == expected
    assert queue.metrics().update_count == case_count
