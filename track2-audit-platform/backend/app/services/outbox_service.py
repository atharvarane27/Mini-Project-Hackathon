"""Durable outbox polling and idempotent heap projection."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.engines.queue.binary_heap import (
    CaseNotFoundError as HeapCaseNotFoundError,
    DuplicateCaseError,
    StaleCaseVersionError,
)
from app.engines.queue.synchronized_queue import SynchronizedCaseQueue
from app.services.case_service import (
    AuditCase,
    CaseRepository,
    CaseState,
    OutboxEvent,
)


@dataclass(frozen=True, slots=True)
class OutboxPollResult:
    claimed: int
    published: int
    failed: int


class OutboxService:
    def __init__(
        self,
        repository: CaseRepository,
        queue: SynchronizedCaseQueue,
        worker_id: str,
        *,
        clock: Callable[[], datetime] | None = None,
        event_lease: timedelta = timedelta(seconds=30),
        retry_delay: timedelta = timedelta(seconds=5),
        max_attempts: int = 3,
    ) -> None:
        normalized_worker = worker_id.strip()
        if not normalized_worker:
            raise ValueError("worker_id must not be empty")
        if event_lease <= timedelta(0) or retry_delay < timedelta(0):
            raise ValueError("outbox durations are invalid")
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        self.repository = repository
        self.queue = queue
        self.worker_id = normalized_worker
        self.clock = clock or (lambda: datetime.now(UTC))
        self.event_lease = event_lease
        self.retry_delay = retry_delay
        self.max_attempts = max_attempts

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("outbox clock must return a timezone-aware value")
        return value.astimezone(UTC)

    def _project_case(self, case: AuditCase) -> None:
        if case.state is not CaseState.QUEUED:
            if self.queue.contains(case.case_id):
                try:
                    self.queue.remove(case.case_id)
                except HeapCaseNotFoundError:
                    pass
            return
        if not self.queue.contains(case.case_id):
            try:
                self.queue.put(case.case_id, case.priority, case.row_version)
            except DuplicateCaseError:
                pass
            return
        try:
            self.queue.update_priority(
                case.case_id,
                case.priority,
                case.row_version,
            )
        except HeapCaseNotFoundError:
            try:
                self.queue.put(case.case_id, case.priority, case.row_version)
            except DuplicateCaseError:
                pass
        except StaleCaseVersionError:
            # Exact replay or an event older than the current heap projection.
            pass

    def rebuild_queue(self) -> int:
        """Recover expired leases, then rebuild the volatile queue from DB truth."""

        now = self._now()
        self.repository.recover_expired_leases(now=now)
        cases = self.repository.list_recoverable_cases()
        for case in cases:
            self._project_case(case)
        return len(cases)

    def _process(self, event: OutboxEvent) -> None:
        if event.event_type != "CASE_QUEUED":
            raise ValueError(f"unsupported outbox event type {event.event_type!r}")
        case = self.repository.get_case(event.entity_id)
        self._project_case(case)

    def poll_once(self, limit: int = 100) -> OutboxPollResult:
        if limit <= 0:
            raise ValueError("limit must be positive")
        now = self._now()
        events = self.repository.claim_outbox_events(
            worker_id=self.worker_id,
            now=now,
            claimed_until=now + self.event_lease,
            limit=limit,
        )
        published = 0
        failed = 0
        for event in events:
            try:
                self._process(event)
            except Exception as error:
                self.repository.fail_outbox_event(
                    event_id=event.event_id,
                    worker_id=self.worker_id,
                    error=f"{type(error).__name__}: {error}",
                    retry_at=self._now() + self.retry_delay,
                    max_attempts=self.max_attempts,
                )
                failed += 1
                continue
            if self.repository.complete_outbox_event(event.event_id, self.worker_id):
                published += 1
            else:
                failed += 1
        return OutboxPollResult(len(events), published, failed)
