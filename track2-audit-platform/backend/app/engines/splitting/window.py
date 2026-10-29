"""Timestamp-ordered sliding windows for transaction splitting candidates."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Sequence

from .partition import PartitionKey, SplittingPolicy, TransferEvent, partition_events


class OutOfOrderEvent(ValueError):
    """Raised when the O(K) streaming scanner receives a late event."""


class WindowCapacityExceeded(RuntimeError):
    """Raised instead of silently dropping data from an oversized live window."""


@dataclass(frozen=True, slots=True)
class SplittingWindowCandidate:
    """P10 candidate passed to P11 for fingerprinting and persistence."""

    policy_version: int
    partition_key: PartitionKey
    transaction_ids: tuple[str, ...]
    amount_sum_minor: int
    transaction_count: int
    window_start: datetime
    window_end: datetime

    def __post_init__(self) -> None:
        if self.transaction_count != len(self.transaction_ids):
            raise ValueError("transaction_count must match transaction_ids")


def _order_key(event: TransferEvent) -> tuple[datetime, str]:
    return event.occurred_at, event.transaction_id


def scan_sorted_partition(
    events: Sequence[TransferEvent],
    partition_key: PartitionKey,
    policy: SplittingPolicy,
) -> list[SplittingWindowCandidate]:
    """Scan one already-sorted partition in O(K) time.

    The boundary is inclusive: an event exactly ``window_minutes`` after the
    oldest event remains in the window. A late event raises an error; callers
    handling live streams must schedule deterministic partition recomputation.
    """

    candidates: list[SplittingWindowCandidate] = []
    window: deque[TransferEvent] = deque()
    running_sum = 0
    previous_order: tuple[datetime, str] | None = None
    duration = timedelta(minutes=policy.window_minutes)

    for event in events:
        current_order = _order_key(event)
        if previous_order is not None and current_order < previous_order:
            raise OutOfOrderEvent(
                f"event {event.transaction_id!r} precedes the streaming watermark"
            )
        previous_order = current_order

        while window and event.occurred_at - window[0].occurred_at > duration:
            running_sum -= window.popleft().amount_minor

        window.append(event)
        running_sum += event.amount_minor
        if len(window) > policy.max_window_events:
            raise WindowCapacityExceeded(
                f"partition {partition_key!r} exceeded {policy.max_window_events} events "
                f"inside {policy.window_minutes} minutes"
            )

        if len(window) >= policy.min_count and running_sum >= policy.amount_threshold_minor:
            candidates.append(
                SplittingWindowCandidate(
                    policy_version=policy.version,
                    partition_key=partition_key,
                    transaction_ids=tuple(item.transaction_id for item in window),
                    amount_sum_minor=running_sum,
                    transaction_count=len(window),
                    window_start=window[0].occurred_at,
                    window_end=window[-1].occurred_at,
                )
            )

    return candidates


def detect_splitting_windows(
    events: Iterable[TransferEvent], policy: SplittingPolicy
) -> list[SplittingWindowCandidate]:
    """Analyze an historical batch deterministically.

    Input may be out of order. Events are deduplicated and filtered, then each
    partition is sorted by UTC timestamp and transaction ID before its O(K)
    scan. Results are returned in a stable order. Overlapping candidate
    suppression and finding fingerprints belong to P11.
    """

    candidates: list[SplittingWindowCandidate] = []
    partitions = partition_events(events, policy)
    ordered_partitions = sorted(partitions.items(), key=lambda item: repr(item[0]))
    for key, partition in ordered_partitions:
        partition.sort(key=_order_key)
        candidates.extend(scan_sorted_partition(partition, key, policy))

    candidates.sort(
        key=lambda candidate: (
            candidate.window_start,
            candidate.window_end,
            repr(candidate.partition_key),
            candidate.transaction_ids,
        )
    )
    return candidates
