"""Temporal and monetary validation of P08 static cycle candidates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass(frozen=True, slots=True)
class CircularTransfer:
    transaction_id: str
    sender_account_id: str
    receiver_account_id: str
    amount_minor: int
    currency: str
    occurred_at: datetime
    status: str = "POSTED"

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.transaction_id,
                self.sender_account_id,
                self.receiver_account_id,
                self.currency,
                self.status,
            )
        ):
            raise ValueError("transfer identifiers and currency must not be empty")
        if isinstance(self.amount_minor, bool) or not isinstance(self.amount_minor, int):
            raise TypeError("amount_minor must be an integer")
        if self.amount_minor <= 0:
            raise ValueError("amount_minor must be positive")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        object.__setattr__(self, "currency", self.currency.strip().upper())
        object.__setattr__(self, "status", self.status.strip().upper())
        object.__setattr__(self, "occurred_at", self.occurred_at.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class CycleCandidate:
    account_path: tuple[str, ...]
    transfers: tuple[CircularTransfer, ...]


@dataclass(frozen=True, slots=True)
class CircularPolicy:
    version: int
    window_minutes: int = 1_440
    min_path_length: int = 3
    max_path_length: int = 8
    min_initial_amount_minor: int = 100_000
    max_amount_variation_bps: int = 1_000

    def __post_init__(self) -> None:
        values = (
            self.version,
            self.window_minutes,
            self.min_path_length,
            self.max_path_length,
            self.min_initial_amount_minor,
            self.max_amount_variation_bps,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise TypeError("circular policy values must be integers")
        if (
            min(values[:-1]) <= 0
            or self.max_amount_variation_bps < 0
            or self.min_path_length > self.max_path_length
        ):
            raise ValueError("circular policy bounds are invalid")
        if self.max_amount_variation_bps > 10_000:
            raise ValueError("amount variation cannot exceed 10000 basis points")


@dataclass(frozen=True, slots=True)
class ValidatedCycle:
    account_path: tuple[str, ...]
    transfers: tuple[CircularTransfer, ...]
    duration: timedelta
    initial_amount_minor: int
    minimum_amount_minor: int
    maximum_amount_minor: int


def validate_cycle(
    candidate: CycleCandidate, policy: CircularPolicy
) -> ValidatedCycle | None:
    transfers = candidate.transfers
    path = candidate.account_path
    length = len(transfers)
    if not policy.min_path_length <= length <= policy.max_path_length:
        return None
    if len(path) != length + 1 or path[0] != path[-1]:
        return None
    if len(set(path[:-1])) != length:
        return None
    if len({transfer.transaction_id for transfer in transfers}) != length:
        return None
    for index, transfer in enumerate(transfers):
        if (
            transfer.sender_account_id != path[index]
            or transfer.receiver_account_id != path[index + 1]
        ):
            return None
    if any(
        transfers[index].occurred_at >= transfers[index + 1].occurred_at
        for index in range(length - 1)
    ):
        return None
    duration = transfers[-1].occurred_at - transfers[0].occurred_at
    if duration > timedelta(minutes=policy.window_minutes):
        return None
    if len({transfer.currency for transfer in transfers}) != 1:
        return None
    initial = transfers[0].amount_minor
    if initial < policy.min_initial_amount_minor:
        return None
    if any(
        abs(transfer.amount_minor - initial) * 10_000
        > initial * policy.max_amount_variation_bps
        for transfer in transfers[1:]
    ):
        return None
    amounts = tuple(transfer.amount_minor for transfer in transfers)
    return ValidatedCycle(
        path,
        transfers,
        duration,
        initial,
        min(amounts),
        max(amounts),
    )
