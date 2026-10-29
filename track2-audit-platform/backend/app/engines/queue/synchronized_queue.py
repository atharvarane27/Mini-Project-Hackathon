"""Explicit Lock/Condition wrapper around the custom binary heap."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Condition, Lock
from time import monotonic

from .binary_heap import (
    BinaryMaxHeap,
    DuplicateCaseError,
    HeapEntry,
    StaleCaseVersionError,
)


class QueueShutdown(RuntimeError):
    pass


class QueueTimeout(TimeoutError):
    pass


@dataclass(frozen=True, slots=True)
class QueueMetrics:
    push_count: int
    pop_count: int
    update_count: int
    remove_count: int
    duplicate_rejections: int
    stale_version_rejections: int
    condition_wait_count: int
    timeout_count: int
    lock_contention_count: int
    max_depth: int
    current_depth: int
    shutdown: bool


class SynchronizedCaseQueue:
    """One-process, multi-thread queue with no unprotected heap access."""

    def __init__(self) -> None:
        self._heap = BinaryMaxHeap()
        self._lock = Lock()
        self._condition = Condition(self._lock)
        self._next_sequence = 0
        self._shutdown = False
        self._push_count = 0
        self._pop_count = 0
        self._update_count = 0
        self._remove_count = 0
        self._duplicate_rejections = 0
        self._stale_version_rejections = 0
        self._condition_wait_count = 0
        self._timeout_count = 0
        self._lock_contention_count = 0
        self._max_depth = 0

    @contextmanager
    def _critical_section(self) -> Iterator[None]:
        if not self._lock.acquire(blocking=False):
            self._lock.acquire()
            self._lock_contention_count += 1
        try:
            yield
        finally:
            self._lock.release()

    def put(self, case_id: str, priority: int, case_version: int) -> HeapEntry:
        with self._critical_section():
            if self._shutdown:
                raise QueueShutdown("queue is shut down")
            entry = HeapEntry(
                priority=priority,
                enqueue_sequence=self._next_sequence,
                case_id=case_id,
                case_version=case_version,
            )
            try:
                self._heap.push(entry)
            except DuplicateCaseError:
                self._duplicate_rejections += 1
                raise
            self._next_sequence += 1
            self._push_count += 1
            self._max_depth = max(self._max_depth, len(self._heap))
            self._condition.notify()
            return entry

    def get(self, timeout: float | None = None) -> HeapEntry:
        if timeout is not None and timeout < 0:
            raise ValueError("timeout must not be negative")
        deadline = None if timeout is None else monotonic() + timeout
        with self._critical_section():
            while len(self._heap) == 0:
                if self._shutdown:
                    raise QueueShutdown("queue is shut down and drained")
                remaining = None if deadline is None else deadline - monotonic()
                if remaining is not None and remaining <= 0:
                    self._timeout_count += 1
                    raise QueueTimeout("timed out waiting for queued case")
                self._condition_wait_count += 1
                self._condition.wait(remaining)
            entry = self._heap.pop()
            self._pop_count += 1
            return entry

    def peek(self) -> HeapEntry:
        with self._critical_section():
            return self._heap.peek()

    def update_priority(
        self, case_id: str, new_priority: int, new_case_version: int
    ) -> HeapEntry:
        with self._critical_section():
            if self._shutdown:
                raise QueueShutdown("queue is shut down")
            try:
                entry = self._heap.update_priority(
                    case_id, new_priority, new_case_version
                )
            except StaleCaseVersionError:
                self._stale_version_rejections += 1
                raise
            self._update_count += 1
            self._condition.notify()
            return entry

    def remove(self, case_id: str) -> HeapEntry:
        with self._critical_section():
            entry = self._heap.remove(case_id)
            self._remove_count += 1
            return entry

    def contains(self, case_id: str) -> bool:
        with self._critical_section():
            return self._heap.contains(case_id)

    def qsize(self) -> int:
        with self._critical_section():
            return len(self._heap)

    def empty(self) -> bool:
        with self._critical_section():
            return len(self._heap) == 0

    def validate_heap(self) -> bool:
        with self._critical_section():
            return self._heap.validate_heap()

    def shutdown(self) -> None:
        """Reject producers, wake consumers, and allow queued work to drain."""

        with self._critical_section():
            self._shutdown = True
            self._condition.notify_all()

    def metrics(self) -> QueueMetrics:
        with self._critical_section():
            return QueueMetrics(
                push_count=self._push_count,
                pop_count=self._pop_count,
                update_count=self._update_count,
                remove_count=self._remove_count,
                duplicate_rejections=self._duplicate_rejections,
                stale_version_rejections=self._stale_version_rejections,
                condition_wait_count=self._condition_wait_count,
                timeout_count=self._timeout_count,
                lock_contention_count=self._lock_contention_count,
                max_depth=self._max_depth,
                current_depth=len(self._heap),
                shutdown=self._shutdown,
            )
