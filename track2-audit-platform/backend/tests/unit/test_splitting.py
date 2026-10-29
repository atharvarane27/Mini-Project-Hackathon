"""P10 acceptance tests for partitioning and sliding windows."""

from __future__ import annotations

import csv
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.engines.splitting.partition import (
    DuplicateTransactionConflict,
    GroupMode,
    PartitionKey,
    ReversalHandling,
    SplittingPolicy,
    TransferEvent,
)
from app.engines.splitting.window import (
    OutOfOrderEvent,
    WindowCapacityExceeded,
    detect_splitting_windows,
    scan_sorted_partition,
)


START = datetime(2024, 1, 1, 10, 0, tzinfo=UTC)


def event(
    transaction_id: str,
    amount_minor: int,
    minute: int,
    *,
    sender: str = "SENDER-1",
    receiver: str = "RECEIVER-1",
    currency: str = "INR",
    transaction_type: str = "TRANSFER",
    **kwargs: object,
) -> TransferEvent:
    return TransferEvent(
        transaction_id=transaction_id,
        sender_account_id=sender,
        receiver_account_id=receiver,
        amount_minor=amount_minor,
        currency=currency,
        occurred_at=START + timedelta(minutes=minute),
        transaction_type=transaction_type,
        **kwargs,
    )


def policy(**kwargs: object) -> SplittingPolicy:
    values: dict[str, object] = {
        "version": 1,
        "window_minutes": 60,
        "amount_threshold_minor": 10_000_000,
        "min_count": 3,
        "individual_max_minor": 9_999_999,
    }
    values.update(kwargs)
    return SplittingPolicy(**values)  # type: ignore[arg-type]


def example_events() -> list[TransferEvent]:
    return [
        event("T-40", 4_000_000, 0),
        event("T-35", 3_500_000, 20),
        event("T-30", 3_000_000, 40),
    ]


def test_three_transfers_inside_window_cross_threshold() -> None:
    candidates = detect_splitting_windows(example_events(), policy())

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.transaction_ids == ("T-40", "T-35", "T-30")
    assert candidate.amount_sum_minor == 10_500_000
    assert candidate.transaction_count == 3
    assert candidate.policy_version == 1


def test_reference_fixture_has_only_the_expected_positive_windows() -> None:
    fixture_path = Path(__file__).resolve().parents[3] / "fixtures" / "splitting_transfers.csv"
    fixture_events: list[TransferEvent] = []
    with fixture_path.open("r", encoding="utf-8", newline="") as fixture_file:
        for row in csv.DictReader(fixture_file):
            fixture_events.append(
                TransferEvent(
                    transaction_id=row["transaction_id"],
                    sender_account_id=row["sender_account_id"],
                    receiver_account_id=row["receiver_account_id"],
                    amount_minor=int(row["amount_minor"]),
                    currency=row["currency"],
                    occurred_at=datetime.fromisoformat(row["occurred_at"]),
                    transaction_type=row["transaction_type"],
                    status=row["status"],
                    is_reversal=row["is_reversal"] == "true",
                    reversal_of_transaction_id=row["reversal_of_transaction_id"] or None,
                    is_fee=row["is_fee"] == "true",
                    is_cash=row["is_cash"] == "true",
                    is_internal=row["is_internal"] == "true",
                )
            )

    candidates = detect_splitting_windows(fixture_events, policy())

    assert [candidate.transaction_ids for candidate in candidates] == [
        ("SPLIT-1", "SPLIT-2", "SPLIT-3"),
        ("BOUNDARY-1", "BOUNDARY-2", "BOUNDARY-3"),
    ]


def test_same_values_outside_window_do_not_trigger() -> None:
    events = [
        event("T-1", 4_000_000, 0),
        event("T-2", 3_500_000, 61),
        event("T-3", 3_000_000, 122),
    ]

    assert detect_splitting_windows(events, policy()) == []


def test_window_boundary_is_inclusive() -> None:
    events = [
        event("T-1", 4_000_000, 0),
        event("T-2", 3_500_000, 30),
        event("T-3", 3_000_000, 60),
    ]

    candidates = detect_splitting_windows(events, policy())

    assert len(candidates) == 1
    assert candidates[0].window_end - candidates[0].window_start == timedelta(minutes=60)


def test_currency_is_always_partitioned() -> None:
    events = [
        event("INR-1", 4_000_000, 0),
        event("INR-2", 4_000_000, 10),
        event("USD-1", 4_000_000, 20, currency="USD"),
    ]

    assert detect_splitting_windows(events, policy()) == []


def test_group_mode_controls_receiver_and_type_partitioning() -> None:
    different_receivers = [
        event("T-1", 4_000_000, 0, receiver="R-1"),
        event("T-2", 3_500_000, 10, receiver="R-2"),
        event("T-3", 3_000_000, 20, receiver="R-3"),
    ]
    assert len(detect_splitting_windows(different_receivers, policy())) == 1
    assert (
        detect_splitting_windows(
            different_receivers, policy(group_mode=GroupMode.SENDER_RECEIVER)
        )
        == []
    )

    different_types = [
        event("K-1", 4_000_000, 0, transaction_type="WIRE"),
        event("K-2", 3_500_000, 10, transaction_type="CARD"),
        event("K-3", 3_000_000, 20, transaction_type="CASH"),
    ]
    assert (
        len(
            detect_splitting_windows(
                different_types, policy(group_mode=GroupMode.SENDER_RECEIVER)
            )
        )
        == 1
    )
    assert (
        detect_splitting_windows(
            different_types, policy(group_mode=GroupMode.SENDER_RECEIVER_TYPE)
        )
        == []
    )


def test_exact_replay_is_counted_once() -> None:
    events = example_events()
    candidates = detect_splitting_windows([events[0], events[0], *events[1:]], policy())

    assert len(candidates) == 1
    assert candidates[0].transaction_count == 3


def test_conflicting_payload_for_same_canonical_id_is_rejected() -> None:
    original = event("T-1", 4_000_000, 0)
    conflicting = replace(original, amount_minor=4_000_001)

    with pytest.raises(DuplicateTransactionConflict, match="conflicting payloads"):
        detect_splitting_windows([original, conflicting], policy())


def test_reversal_policy_can_exclude_pair_or_only_reversal() -> None:
    originals = example_events()
    reversal = event(
        "REV-T-30",
        3_000_000,
        45,
        is_reversal=True,
        reversal_of_transaction_id="T-30",
    )

    assert detect_splitting_windows([*originals, reversal], policy()) == []
    candidates = detect_splitting_windows(
        [*originals, reversal],
        policy(reversal_handling=ReversalHandling.EXCLUDE_REVERSAL),
    )
    assert len(candidates) == 1
    assert "REV-T-30" not in candidates[0].transaction_ids

    pending_reversal = replace(reversal, status="PENDING")
    candidates = detect_splitting_windows([*originals, pending_reversal], policy())
    assert len(candidates) == 1


def test_historical_batch_sorts_out_of_order_input_deterministically() -> None:
    events = example_events()

    forward = detect_splitting_windows(events, policy())
    reverse = detect_splitting_windows(list(reversed(events)), policy())

    assert reverse == forward


def test_linear_scanner_rejects_late_arrival() -> None:
    events = example_events()
    key = PartitionKey("SENDER-1", "INR")

    with pytest.raises(OutOfOrderEvent, match="streaming watermark"):
        scan_sorted_partition([events[1], events[0]], key, policy())


def test_status_amount_and_explicit_category_filters() -> None:
    base = example_events()
    pending = replace(base[2], status="PENDING")
    too_large = replace(base[2], amount_minor=10_000_000)
    cash = replace(base[2], is_cash=True)
    fee = replace(base[2], is_fee=True)
    internal = replace(base[2], is_internal=True)
    self_transfer = replace(
        base[2], receiver_account_id=base[2].sender_account_id
    )

    for excluded in (pending, too_large, cash, fee, internal, self_transfer):
        assert detect_splitting_windows([base[0], base[1], excluded], policy()) == []

    included = detect_splitting_windows(
        [base[0], base[1], cash], policy(include_cash=True)
    )
    assert len(included) == 1


def test_transaction_type_allowlist_is_normalized() -> None:
    events = example_events()
    allowed = policy(included_transaction_types=frozenset({"transfer"}))
    blocked = policy(included_transaction_types=frozenset({"wire"}))

    assert len(detect_splitting_windows(events, allowed)) == 1
    assert detect_splitting_windows(events, blocked) == []


def test_window_capacity_is_bounded_and_fails_loudly() -> None:
    events = [event(f"T-{index}", 1, index) for index in range(4)]
    bounded_policy = policy(
        min_count=2,
        amount_threshold_minor=100,
        individual_max_minor=99,
        max_window_events=3,
    )

    with pytest.raises(WindowCapacityExceeded, match="exceeded 3 events"):
        detect_splitting_windows(events, bounded_policy)


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"window_minutes": 0}, "window_minutes"),
        ({"min_count": 1}, "min_count"),
        ({"individual_max_minor": 10_000_000}, "individual_max_minor"),
        ({"max_window_events": 2}, "max_window_events"),
    ],
)
def test_invalid_policy_is_rejected(changes: dict[str, object], error: str) -> None:
    with pytest.raises((TypeError, ValueError), match=error):
        policy(**changes)


def test_transfer_requires_integer_money_and_aware_timestamp() -> None:
    with pytest.raises(TypeError, match="integer"):
        event("T-FLOAT", 1.5, 0)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="timezone-aware"):
        replace(event("T-NAIVE", 100, 0), occurred_at=datetime(2024, 1, 1))
