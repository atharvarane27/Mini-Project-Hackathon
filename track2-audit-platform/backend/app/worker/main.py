"""Single-owner worker composition for durable outbox and case claims."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

from app.engines.queue.claim_service import ClaimService
from app.engines.queue.synchronized_queue import SynchronizedCaseQueue
from app.services.case_service import AuditCase, CaseRepository
from app.services.outbox_service import OutboxPollResult, OutboxService


class CaseWorker:
    """Own one heap; database calls happen outside the heap critical section."""

    def __init__(
        self,
        repository: CaseRepository,
        worker_id: str,
        *,
        clock: Callable[[], datetime] | None = None,
        case_lease: timedelta = timedelta(minutes=5),
    ) -> None:
        self.queue = SynchronizedCaseQueue()
        self.outbox = OutboxService(
            repository,
            self.queue,
            worker_id,
            clock=clock,
        )
        self.claims = ClaimService(
            repository,
            self.queue,
            worker_id,
            clock=clock,
            lease_duration=case_lease,
        )

    def start(self) -> int:
        return self.outbox.rebuild_queue()

    def poll_once(self, limit: int = 100) -> OutboxPollResult:
        return self.outbox.poll_once(limit)

    def claim_next(self, timeout: float | None = None) -> AuditCase:
        return self.claims.claim_next(timeout)

    def shutdown(self) -> None:
        self.queue.shutdown()
