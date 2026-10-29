"""Custom indexed binary max heap for prioritized audit cases.

The heap contains no synchronization. ``SynchronizedCaseQueue`` owns the one
mutex that protects every access to an instance used by worker threads.
"""

from __future__ import annotations

from dataclasses import dataclass


class EmptyHeapError(IndexError):
    pass


class DuplicateCaseError(ValueError):
    pass


class CaseNotFoundError(KeyError):
    pass


class StaleCaseVersionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class HeapEntry:
    priority: int
    enqueue_sequence: int
    case_id: str
    case_version: int

    def __post_init__(self) -> None:
        for name in ("priority", "enqueue_sequence", "case_version"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
            if value < 0:
                raise ValueError(f"{name} must not be negative")
        if not self.case_id.strip():
            raise ValueError("case_id must not be empty")
        object.__setattr__(self, "case_id", self.case_id.strip())


def _higher_priority(left: HeapEntry, right: HeapEntry) -> bool:
    """Return True when left must be popped before right."""

    if left.priority != right.priority:
        return left.priority > right.priority
    if left.enqueue_sequence != right.enqueue_sequence:
        return left.enqueue_sequence < right.enqueue_sequence
    if left.case_id != right.case_id:
        return left.case_id < right.case_id
    return left.case_version > right.case_version


class BinaryMaxHeap:
    """Array heap plus case-ID position map, with O(log N) mutations."""

    def __init__(self) -> None:
        self._entries: list[HeapEntry] = []
        self._positions: dict[str, int] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def size(self) -> int:
        return len(self._entries)

    def contains(self, case_id: str) -> bool:
        return case_id in self._positions

    def push(self, entry: HeapEntry) -> None:
        if entry.case_id in self._positions:
            raise DuplicateCaseError(f"case {entry.case_id!r} is already queued")
        index = len(self._entries)
        self._entries.append(entry)
        self._positions[entry.case_id] = index
        self._sift_up(index)

    def peek(self) -> HeapEntry:
        if not self._entries:
            raise EmptyHeapError("heap is empty")
        return self._entries[0]

    def pop(self) -> HeapEntry:
        if not self._entries:
            raise EmptyHeapError("heap is empty")
        return self._remove_at(0)

    def remove(self, case_id: str) -> HeapEntry:
        try:
            index = self._positions[case_id]
        except KeyError as error:
            raise CaseNotFoundError(f"case {case_id!r} is not queued") from error
        return self._remove_at(index)

    def update_priority(
        self,
        case_id: str,
        new_priority: int,
        new_case_version: int,
    ) -> HeapEntry:
        try:
            index = self._positions[case_id]
        except KeyError as error:
            raise CaseNotFoundError(f"case {case_id!r} is not queued") from error
        current = self._entries[index]
        updated = HeapEntry(
            priority=new_priority,
            enqueue_sequence=current.enqueue_sequence,
            case_id=current.case_id,
            case_version=new_case_version,
        )
        if updated.case_version <= current.case_version:
            raise StaleCaseVersionError(
                f"case {case_id!r} version {updated.case_version} is not newer than "
                f"queued version {current.case_version}"
            )
        self._entries[index] = updated
        if _higher_priority(updated, current):
            self._sift_up(index)
        else:
            self._sift_down(index)
        return updated

    def snapshot(self) -> tuple[HeapEntry, ...]:
        return tuple(self._entries)

    def validate_heap(self) -> bool:
        if len(self._entries) != len(self._positions):
            return False
        for index, entry in enumerate(self._entries):
            if self._positions.get(entry.case_id) != index:
                return False
            left = 2 * index + 1
            right = left + 1
            if left < len(self._entries) and _higher_priority(
                self._entries[left], entry
            ):
                return False
            if right < len(self._entries) and _higher_priority(
                self._entries[right], entry
            ):
                return False
        return True

    def _remove_at(self, index: int) -> HeapEntry:
        removed = self._entries[index]
        last = self._entries.pop()
        del self._positions[removed.case_id]
        if index < len(self._entries):
            self._entries[index] = last
            self._positions[last.case_id] = index
            parent = (index - 1) // 2
            if index > 0 and _higher_priority(self._entries[index], self._entries[parent]):
                self._sift_up(index)
            else:
                self._sift_down(index)
        return removed

    def _swap(self, left: int, right: int) -> None:
        self._entries[left], self._entries[right] = (
            self._entries[right],
            self._entries[left],
        )
        self._positions[self._entries[left].case_id] = left
        self._positions[self._entries[right].case_id] = right

    def _sift_up(self, index: int) -> None:
        while index > 0:
            parent = (index - 1) // 2
            if not _higher_priority(self._entries[index], self._entries[parent]):
                return
            self._swap(index, parent)
            index = parent

    def _sift_down(self, index: int) -> None:
        size = len(self._entries)
        while True:
            left = 2 * index + 1
            if left >= size:
                return
            right = left + 1
            best = left
            if right < size and _higher_priority(
                self._entries[right], self._entries[left]
            ):
                best = right
            if not _higher_priority(self._entries[best], self._entries[index]):
                return
            self._swap(index, best)
            index = best
