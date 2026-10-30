"""Single-owner worker composition for durable outbox and case claims."""

from __future__ import annotations

import json
import logging
import signal
from collections.abc import Callable
from datetime import datetime, timedelta
from threading import Event

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


def main() -> None:
    """Keep the dedicated worker process alive until persistence is composed."""

    logging.basicConfig(level="INFO", format="%(message)s")
    logger = logging.getLogger("auditforge.worker")
    stopped = Event()

    def request_stop(_signum: int, _frame: object) -> None:
        stopped.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    logger.info(json.dumps({"event": "worker_started", "mode": "single-owner"}))
    stopped.wait()
    logger.info(json.dumps({"event": "worker_stopped"}))


if __name__ == "__main__":
    main()
