"""P15 unit tests for the custom heap and synchronized queue."""

from __future__ import annotations

import inspect
import random
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

import app.engines.queue.binary_heap as heap_module
import app.engines.queue.synchronized_queue as queue_module
from app.engines.queue.binary_heap import (
    BinaryMaxHeap,
    CaseNotFoundError,
    DuplicateCaseError,
    EmptyHeapError,
    HeapEntry,
    StaleCaseVersionError,
)
from app.engines.queue.synchronized_queue import (
    QueueShutdown,
    QueueTimeout,
    SynchronizedCaseQueue,
)


def entry(
    case_id: str,
    priority: int,
    sequence: int,
    version: int = 1,
) -> HeapEntry:
    return HeapEntry(priority, sequence, case_id, version)


def wait_until_waiting(queue: SynchronizedCaseQueue) -> None:
    deadline = time.monotonic() + 2
    while queue.metrics().condition_wait_count == 0:
        if time.monotonic() >= deadline:
            raise AssertionError("consumer did not enter condition wait")
        time.sleep(0.001)


def test_queue_uses_custom_heap_and_explicit_mutex_condition() -> None:
    heap_source = inspect.getsource(heap_module)
    queue_source = inspect.getsource(queue_module)

    assert "heapq" not in heap_source
    assert "Lock()" in queue_source
    assert "Condition(self._lock)" in queue_source


def test_heap_pops_highest_priority_then_oldest_sequence() -> None:
    heap = BinaryMaxHeap()
    for item in (
        entry("low", 10, 0),
        entry("new-high", 100, 5),
        entry("old-high", 100, 2),
        entry("middle", 50, 1),
    ):
        heap.push(item)

    assert heap.validate_heap()
    assert [heap.pop().case_id for _ in range(4)] == [
        "old-high",
        "new-high",
        "middle",
        "low",
    ]


def test_heap_has_deterministic_fallback_for_identical_priority_and_sequence() -> None:
    heap = BinaryMaxHeap()
    heap.push(entry("case-b", 10, 1))
    heap.push(entry("case-a", 10, 1))

    assert heap.pop().case_id == "case-a"
    assert heap.pop().case_id == "case-b"


def test_peek_does_not_remove_and_empty_operations_fail() -> None:
    heap = BinaryMaxHeap()
    with pytest.raises(EmptyHeapError):
        heap.peek()
    with pytest.raises(EmptyHeapError):
        heap.pop()

    heap.push(entry("case-1", 5, 0))
    assert heap.peek().case_id == "case-1"
    assert heap.size() == 1


def test_duplicate_case_id_is_rejected() -> None:
    heap = BinaryMaxHeap()
    heap.push(entry("same", 5, 0))

    with pytest.raises(DuplicateCaseError, match="already queued"):
        heap.push(entry("same", 100, 1, 2))

    assert heap.size() == 1
    assert heap.validate_heap()


def test_priority_update_moves_both_up_and_down_without_duplicate_entry() -> None:
    heap = BinaryMaxHeap()
    heap.push(entry("a", 10, 0, 1))
    heap.push(entry("b", 20, 1, 1))
    heap.push(entry("c", 30, 2, 1))

    raised = heap.update_priority("a", 40, 2)
    assert raised.enqueue_sequence == 0
    assert heap.peek().case_id == "a"
    lowered = heap.update_priority("a", 1, 3)
    assert lowered.case_version == 3
    assert heap.peek().case_id == "c"
    assert heap.size() == 3
    assert heap.validate_heap()


def test_stale_version_and_unknown_update_are_rejected() -> None:
    heap = BinaryMaxHeap()
    heap.push(entry("a", 10, 0, 4))

    with pytest.raises(StaleCaseVersionError, match="not newer"):
        heap.update_priority("a", 20, 4)
    with pytest.raises(CaseNotFoundError):
        heap.update_priority("missing", 20, 5)


def test_remove_repairs_position_map_and_heap_order() -> None:
    heap = BinaryMaxHeap()
    for index in range(20):
        heap.push(entry(f"case-{index}", index, index))

    removed = heap.remove("case-10")

    assert removed.case_id == "case-10"
    assert not heap.contains("case-10")
    assert heap.validate_heap()
    with pytest.raises(CaseNotFoundError):
        heap.remove("case-10")


def test_randomized_heap_matches_reference_order() -> None:
    randomizer = random.Random(20261029)
    entries = [
        entry(f"case-{index:04d}", randomizer.randrange(0, 101), index)
        for index in range(1_000)
    ]
    insertion_order = entries.copy()
    randomizer.shuffle(insertion_order)
    heap = BinaryMaxHeap()
    for item in insertion_order:
        heap.push(item)
        assert heap.validate_heap()

    expected = sorted(
        entries,
        key=lambda item: (-item.priority, item.enqueue_sequence, item.case_id),
    )
    actual = [heap.pop() for _ in entries]

    assert actual == expected
    assert heap.validate_heap()


@pytest.mark.parametrize(
    "values",
    [
        (-1, 0, "case", 1),
        (1, -1, "case", 1),
        (1, 0, "", 1),
        (1, 0, "case", -1),
        (True, 0, "case", 1),
    ],
)
def test_heap_entry_validates_fields(values: tuple[object, object, str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        HeapEntry(*values)  # type: ignore[arg-type]


def test_queue_assigns_sequence_and_preserves_tie_order() -> None:
    queue = SynchronizedCaseQueue()
    first = queue.put("first", 10, 1)
    second = queue.put("second", 10, 1)

    assert (first.enqueue_sequence, second.enqueue_sequence) == (0, 1)
    assert queue.get().case_id == "first"
    assert queue.get().case_id == "second"
    assert queue.empty()


def test_blocking_consumer_wakes_when_case_is_enqueued() -> None:
    queue = SynchronizedCaseQueue()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(queue.get, 2.0)
        wait_until_waiting(queue)
        queue.put("wake-up", 50, 1)
        result = future.result(timeout=2)

    assert result.case_id == "wake-up"
    metrics = queue.metrics()
    assert metrics.condition_wait_count >= 1
    assert metrics.push_count == metrics.pop_count == 1


def test_get_timeout_is_controlled_and_counted() -> None:
    queue = SynchronizedCaseQueue()

    with pytest.raises(QueueTimeout):
        queue.get(timeout=0.01)

    assert queue.metrics().timeout_count == 1
    with pytest.raises(ValueError, match="negative"):
        queue.get(timeout=-1)


def test_shutdown_drains_existing_work_and_wakes_waiters() -> None:
    draining = SynchronizedCaseQueue()
    draining.put("queued", 1, 1)
    draining.shutdown()
    assert draining.get().case_id == "queued"
    with pytest.raises(QueueShutdown, match="drained"):
        draining.get()
    with pytest.raises(QueueShutdown):
        draining.put("new", 1, 1)

    waiting = SynchronizedCaseQueue()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(waiting.get, None)
        wait_until_waiting(waiting)
        waiting.shutdown()
        with pytest.raises(QueueShutdown):
            future.result(timeout=2)


def test_queue_duplicate_stale_update_remove_and_metrics() -> None:
    queue = SynchronizedCaseQueue()
    queue.put("case-1", 10, 1)
    with pytest.raises(DuplicateCaseError):
        queue.put("case-1", 20, 2)
    with pytest.raises(StaleCaseVersionError):
        queue.update_priority("case-1", 20, 1)
    updated = queue.update_priority("case-1", 20, 2)
    assert updated.priority == 20
    assert queue.contains("case-1")
    assert queue.peek() == updated
    assert queue.remove("case-1") == updated
    assert queue.validate_heap()

    metrics = queue.metrics()
    assert metrics.push_count == 1
    assert metrics.update_count == 1
    assert metrics.remove_count == 1
    assert metrics.duplicate_rejections == 1
    assert metrics.stale_version_rejections == 1
    assert metrics.max_depth == 1
    assert metrics.current_depth == 0
