"""Partition and eligibility rules for deterministic transaction splitting.

This module is intentionally independent of persistence and API models. A P04
canonical transaction can be adapted to :class:`TransferEvent` at the engine
boundary without making the detector depend on SQLAlchemy or Pydantic.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Iterable


class GroupMode(StrEnum):
    """Supported deterministic partition shapes.

    Currency is always part of a key so amounts from different currencies are
    never aggregated.
    """

    SENDER = "SENDER"
    SENDER_RECEIVER = "SENDER_RECEIVER"
    SENDER_RECEIVER_TYPE = "SENDER_RECEIVER_TYPE"


class ReversalHandling(StrEnum):
    """How reversal records affect an analysis batch."""

    EXCLUDE_BOTH = "EXCLUDE_BOTH"
    EXCLUDE_REVERSAL = "EXCLUDE_REVERSAL"
    INCLUDE = "INCLUDE"


class DuplicateTransactionConflict(ValueError):
    """Raised when one canonical ID identifies two different transactions."""


@dataclass(frozen=True, slots=True)
class TransferEvent:
    """Minimal immutable P10 view of an accepted canonical transfer."""

    transaction_id: str
    sender_account_id: str
    receiver_account_id: str
    amount_minor: int
    currency: str
    occurred_at: datetime
    transaction_type: str
    status: str = "POSTED"
    is_reversal: bool = False
    reversal_of_transaction_id: str | None = None
    is_fee: bool = False
    is_cash: bool = False
    is_internal: bool = False

    def __post_init__(self) -> None:
        if not self.transaction_id.strip():
            raise ValueError("transaction_id must not be empty")
        if not self.sender_account_id.strip():
            raise ValueError("sender_account_id must not be empty")
        if not self.receiver_account_id.strip():
            raise ValueError("receiver_account_id must not be empty")
        if isinstance(self.amount_minor, bool) or not isinstance(self.amount_minor, int):
            raise TypeError("amount_minor must be an integer")
        if self.amount_minor <= 0:
            raise ValueError("amount_minor must be positive")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        if not self.currency.strip():
            raise ValueError("currency must not be empty")
        if not self.transaction_type.strip():
            raise ValueError("transaction_type must not be empty")
        if self.reversal_of_transaction_id == self.transaction_id:
            raise ValueError("a transaction cannot reverse itself")

        object.__setattr__(self, "transaction_id", self.transaction_id.strip())
        object.__setattr__(self, "sender_account_id", self.sender_account_id.strip())
        object.__setattr__(self, "receiver_account_id", self.receiver_account_id.strip())
        object.__setattr__(self, "currency", self.currency.strip().upper())
        object.__setattr__(self, "transaction_type", self.transaction_type.strip().upper())
        object.__setattr__(self, "status", self.status.strip().upper())
        object.__setattr__(self, "occurred_at", self.occurred_at.astimezone(UTC))
        if self.reversal_of_transaction_id is not None:
            target = self.reversal_of_transaction_id.strip()
            if not target:
                raise ValueError("reversal_of_transaction_id cannot be blank")
            if target == self.transaction_id:
                raise ValueError("a transaction cannot reverse itself")
            object.__setattr__(self, "reversal_of_transaction_id", target)


@dataclass(frozen=True, slots=True)
class SplittingPolicy:
    """Versioned parameters controlling eligibility, grouping and windows."""

    version: int
    window_minutes: int = 60
    amount_threshold_minor: int = 10_000_000
    min_count: int = 3
    individual_max_minor: int = 9_999_999
    group_mode: GroupMode = GroupMode.SENDER
    accepted_statuses: frozenset[str] = frozenset({"POSTED"})
    reversal_handling: ReversalHandling = ReversalHandling.EXCLUDE_BOTH
    include_fees: bool = False
    include_cash: bool = False
    include_internal: bool = False
    included_transaction_types: frozenset[str] | None = None
    max_window_events: int = 10_000

    def __post_init__(self) -> None:
        integer_fields = {
            "version": self.version,
            "window_minutes": self.window_minutes,
            "amount_threshold_minor": self.amount_threshold_minor,
            "min_count": self.min_count,
            "individual_max_minor": self.individual_max_minor,
            "max_window_events": self.max_window_events,
        }
        for name, value in integer_fields.items():
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{name} must be an integer")
        if self.version <= 0:
            raise ValueError("version must be positive")
        if self.window_minutes <= 0:
            raise ValueError("window_minutes must be positive")
        if self.amount_threshold_minor <= 0:
            raise ValueError("amount_threshold_minor must be positive")
        if self.min_count < 2:
            raise ValueError("min_count must be at least 2")
        if not 0 < self.individual_max_minor < self.amount_threshold_minor:
            raise ValueError("individual_max_minor must be positive and below the threshold")
        if self.max_window_events < self.min_count:
            raise ValueError("max_window_events must be at least min_count")
        if not self.accepted_statuses:
            raise ValueError("accepted_statuses must not be empty")

        object.__setattr__(self, "group_mode", GroupMode(self.group_mode))
        object.__setattr__(
            self, "reversal_handling", ReversalHandling(self.reversal_handling)
        )

        normalized_statuses = frozenset(
            status.strip().upper() for status in self.accepted_statuses
        )
        if "" in normalized_statuses:
            raise ValueError("accepted_statuses cannot contain a blank value")
        object.__setattr__(
            self,
            "accepted_statuses",
            normalized_statuses,
        )
        if self.included_transaction_types is not None:
            if not self.included_transaction_types:
                raise ValueError("included_transaction_types cannot be empty")
            normalized_types = frozenset(
                value.strip().upper() for value in self.included_transaction_types
            )
            if "" in normalized_types:
                raise ValueError("included_transaction_types cannot contain a blank value")
            object.__setattr__(
                self,
                "included_transaction_types",
                normalized_types,
            )


@dataclass(frozen=True, slots=True)
class PartitionKey:
    """Hashable and inspectable grouping key."""

    sender_account_id: str
    currency: str
    receiver_account_id: str | None = None
    transaction_type: str | None = None


def partition_key(event: TransferEvent, policy: SplittingPolicy) -> PartitionKey:
    """Build a policy-specific key while always preserving currency isolation."""

    if policy.group_mode is GroupMode.SENDER:
        return PartitionKey(event.sender_account_id, event.currency)
    if policy.group_mode is GroupMode.SENDER_RECEIVER:
        return PartitionKey(
            event.sender_account_id,
            event.currency,
            receiver_account_id=event.receiver_account_id,
        )
    return PartitionKey(
        event.sender_account_id,
        event.currency,
        receiver_account_id=event.receiver_account_id,
        transaction_type=event.transaction_type,
    )


def _deduplicate(events: Iterable[TransferEvent]) -> list[TransferEvent]:
    """Drop exact replays and reject conflicting reuse of a canonical ID."""

    by_id: dict[str, TransferEvent] = {}
    for event in events:
        existing = by_id.get(event.transaction_id)
        if existing is None:
            by_id[event.transaction_id] = event
        elif existing != event:
            raise DuplicateTransactionConflict(
                f"canonical transaction {event.transaction_id!r} has conflicting payloads"
            )
    return list(by_id.values())


def eligible_events(
    events: Iterable[TransferEvent], policy: SplittingPolicy
) -> list[TransferEvent]:
    """Return deduplicated events admitted by the explicit policy."""

    unique_events = _deduplicate(events)
    reversed_ids = {
        event.reversal_of_transaction_id
        for event in unique_events
        if event.is_reversal
        and event.reversal_of_transaction_id
        and event.status in policy.accepted_statuses
    }

    admitted: list[TransferEvent] = []
    for event in unique_events:
        if event.status not in policy.accepted_statuses:
            continue
        if event.amount_minor > policy.individual_max_minor:
            continue
        if policy.reversal_handling is not ReversalHandling.INCLUDE and event.is_reversal:
            continue
        if (
            policy.reversal_handling is ReversalHandling.EXCLUDE_BOTH
            and event.transaction_id in reversed_ids
        ):
            continue
        if event.is_fee and not policy.include_fees:
            continue
        if event.is_cash and not policy.include_cash:
            continue
        if (
            event.is_internal or event.sender_account_id == event.receiver_account_id
        ) and not policy.include_internal:
            continue
        if (
            policy.included_transaction_types is not None
            and event.transaction_type not in policy.included_transaction_types
        ):
            continue
        admitted.append(event)
    return admitted


def partition_events(
    events: Iterable[TransferEvent], policy: SplittingPolicy
) -> dict[PartitionKey, list[TransferEvent]]:
    """Deduplicate, filter and group events without changing their order."""

    partitions: defaultdict[PartitionKey, list[TransferEvent]] = defaultdict(list)
    for event in eligible_events(events, policy):
        partitions[partition_key(event, policy)].append(event)
    return dict(partitions)
