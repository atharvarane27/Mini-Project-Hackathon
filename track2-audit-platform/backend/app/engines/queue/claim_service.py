"""Pop heap entries and finalize ownership with a database CAS claim."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from app.engines.queue.binary_heap import DuplicateCaseError
from app.engines.queue.synchronized_queue import SynchronizedCaseQueue
from app.services.case_service import AuditCase, CaseRepository, CaseState


class ClaimConflictError(RuntimeError):
    pass


class ClaimService:
    def __init__(
        self,
        repository: CaseRepository,
        queue: SynchronizedCaseQueue,
        worker_id: str,
        *,
        clock: Callable[[], datetime] | None = None,
        lease_duration: timedelta = timedelta(minutes=5),
    ) -> None:
        normalized_worker = worker_id.strip()
        if not normalized_worker:
            raise ValueError("worker_id must not be empty")
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        self.repository = repository
        self.queue = queue
        self.worker_id = normalized_worker
        self.clock = clock or (lambda: datetime.now(UTC))
        self.lease_duration = lease_duration

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("claim clock must return a timezone-aware value")
        return value.astimezone(UTC)

    def claim_next(self, timeout: float | None = None) -> AuditCase:
        # get() releases the heap lock before the repository/network operation.
        entry = self.queue.get(timeout)
        now = self._now()
        claimed = self.repository.compare_and_swap_claim(
            case_id=entry.case_id,
            expected_version=entry.case_version,
            worker_id=self.worker_id,
            now=now,
            lease_until=now + self.lease_duration,
        )
        if claimed is not None:
            return claimed

        # A failed CAS means the popped projection was stale. Only requeue when
        # database truth is still QUEUED at a newer version.
        current = self.repository.get_case(entry.case_id)
        if current.state is CaseState.QUEUED and current.row_version > entry.case_version:
            try:
                self.queue.put(current.case_id, current.priority, current.row_version)
            except DuplicateCaseError:
                pass
        raise ClaimConflictError(
            f"case {entry.case_id!r} was already claimed or the heap entry was stale"
        )
