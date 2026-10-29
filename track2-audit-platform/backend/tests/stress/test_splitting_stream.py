"""P11 load and contention checks for splitting run orchestration."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from app.engines.splitting.partition import SplittingPolicy, TransferEvent
from app.engines.splitting.service import (
    InMemorySplittingRunRepository,
    run_splitting_detector,
)


def policy() -> SplittingPolicy:
    return SplittingPolicy(
        version=1,
        window_minutes=60,
        amount_threshold_minor=10_000_000,
        min_count=3,
        individual_max_minor=9_999_999,
        max_window_events=100,
    )


def account_events(account_count: int) -> list[TransferEvent]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    events: list[TransferEvent] = []
    for account in range(account_count):
        for part, amount in enumerate((4_000_000, 3_500_000, 3_000_000)):
            events.append(
                TransferEvent(
                    transaction_id=f"T-{account}-{part}",
                    sender_account_id=f"S-{account}",
                    receiver_account_id=f"R-{account}-{part}",
                    amount_minor=amount,
                    currency="INR",
                    occurred_at=start + timedelta(minutes=part * 20),
                    transaction_type="TRANSFER",
                )
            )
    return events


def test_many_partitions_produce_one_finding_each() -> None:
    repository = InMemorySplittingRunRepository()

    outcome = run_splitting_detector(
        reversed(account_events(2_000)),
        policy(),
        "many-partitions-checkpoint",
        repository,
    )

    assert len(outcome.run.findings) == 2_000
    assert repository.finding_count == 2_000
    assert all(
        finding.draft.facts["Splitting_Window_Count"] == 3
        for finding in outcome.run.findings
    )


def test_concurrent_retries_commit_one_logical_run() -> None:
    repository = InMemorySplittingRunRepository()
    events = account_events(1)

    def execute(_: int) -> tuple[str, str, bool]:
        outcome = run_splitting_detector(
            events, policy(), "concurrent-checkpoint", repository
        )
        return (
            outcome.run.run_id,
            outcome.run.findings[0].finding_id,
            outcome.replayed,
        )

    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(execute, range(50)))

    assert len({run_id for run_id, _, _ in results}) == 1
    assert len({finding_id for _, finding_id, _ in results}) == 1
    assert sum(not replayed for _, _, replayed in results) == 1
    assert repository.run_count == 1
    assert repository.finding_count == 1
