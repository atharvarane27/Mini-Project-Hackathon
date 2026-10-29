"""P16 durable outbox replay, retry, and worker restart tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.engines.queue.synchronized_queue import SynchronizedCaseQueue
from app.services.case_service import (
    CaseService,
    InMemoryCaseRepository,
    OutboxState,
)
from app.services.outbox_service import OutboxService
from app.worker.main import CaseWorker


NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


def test_pending_event_projects_case_once_and_is_published() -> None:
    repository = InMemoryCaseRepository()
    cases = CaseService(repository, clock=lambda: NOW)
    case = cases.create_from_findings(["finding-1"], "rule-v1", 80, "system")
    queue = SynchronizedCaseQueue()
    outbox = OutboxService(repository, queue, "worker-1", clock=lambda: NOW)

    result = outbox.poll_once()

    assert (result.claimed, result.published, result.failed) == (1, 1, 0)
    assert queue.qsize() == 1
    assert queue.peek().case_id == case.case_id
    assert repository.list_outbox_events()[0].status is OutboxState.PUBLISHED
    assert outbox.poll_once().claimed == 0
    assert queue.qsize() == 1


def test_crash_after_projection_replays_idempotently_after_event_lease() -> None:
    repository = InMemoryCaseRepository()
    cases = CaseService(repository, clock=lambda: NOW)
    case = cases.create_from_findings(["finding-1"], "rule-v1", 80, "system")
    queue = SynchronizedCaseQueue()
    claimed_event = repository.claim_outbox_events(
        worker_id="dead-worker",
        now=NOW,
        claimed_until=NOW + timedelta(seconds=5),
        limit=1,
    )[0]
    queue.put(case.case_id, case.priority, case.row_version)

    restarted = OutboxService(
        repository,
        queue,
        "replacement-worker",
        clock=lambda: NOW + timedelta(seconds=6),
    )
    result = restarted.poll_once()

    assert claimed_event.status is OutboxState.PROCESSING
    assert result.published == 1
    assert queue.qsize() == 1
    assert repository.list_outbox_events()[0].attempt_count == 2


def test_new_worker_rebuilds_queue_from_database_after_memory_loss() -> None:
    repository = InMemoryCaseRepository()
    cases = CaseService(repository, clock=lambda: NOW)
    case = cases.create_from_findings(["finding-restart"], "rule-v1", 90, "system")
    first = CaseWorker(repository, "worker-before-crash", clock=lambda: NOW)
    first.poll_once()
    assert first.queue.qsize() == 1

    replacement = CaseWorker(repository, "worker-after-crash", clock=lambda: NOW)
    rebuilt = replacement.start()
    replacement.start()

    assert rebuilt == 1
    assert replacement.queue.qsize() == 1
    assert replacement.queue.peek().case_id == case.case_id


def test_failed_delivery_retries_then_moves_to_dead_letter() -> None:
    repository = InMemoryCaseRepository()
    cases = CaseService(repository, clock=lambda: NOW)
    cases.create_from_findings(["finding-dead"], "rule-v1", 40, "system")
    queue = SynchronizedCaseQueue()
    queue.shutdown()
    outbox = OutboxService(
        repository,
        queue,
        "worker-1",
        clock=lambda: NOW,
        retry_delay=timedelta(0),
        max_attempts=3,
    )

    assert outbox.poll_once().failed == 1
    assert outbox.poll_once().failed == 1
    assert outbox.poll_once().failed == 1

    event = repository.list_outbox_events()[0]
    assert event.status is OutboxState.DEAD_LETTER
    assert event.attempt_count == 3
    assert "QueueShutdown" in (event.last_error or "")
    assert outbox.poll_once().claimed == 0


def test_only_one_outbox_poller_can_own_an_event_lease() -> None:
    repository = InMemoryCaseRepository()
    CaseService(repository, clock=lambda: NOW).create_from_findings(
        ["finding-1"], "rule-v1", 40, "system"
    )

    first = repository.claim_outbox_events(
        worker_id="worker-1",
        now=NOW,
        claimed_until=NOW + timedelta(seconds=30),
        limit=1,
    )
    second = repository.claim_outbox_events(
        worker_id="worker-2",
        now=NOW,
        claimed_until=NOW + timedelta(seconds=30),
        limit=1,
    )

    assert len(first) == 1
    assert second == ()


def test_stale_outbox_event_removes_projection_when_case_is_already_claimed() -> None:
    repository = InMemoryCaseRepository()
    cases = CaseService(repository, clock=lambda: NOW)
    case = cases.create_from_findings(["finding-stale"], "rule-v1", 40, "system")
    queue = SynchronizedCaseQueue()
    queue.put(case.case_id, case.priority, case.row_version)
    cases.claim_direct(case.case_id, 1, "other-worker", timedelta(minutes=5))

    result = OutboxService(
        repository, queue, "outbox-worker", clock=lambda: NOW
    ).poll_once()

    assert result.published == 1
    assert queue.empty()
