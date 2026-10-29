"""P16 adversarial compare-and-swap claim tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from app.engines.queue.claim_service import ClaimConflictError
from app.services.case_service import (
    CaseConflictError,
    CaseService,
    CaseState,
    InMemoryCaseRepository,
)
from app.worker.main import CaseWorker


NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


def test_fifty_concurrent_api_style_claims_have_exactly_one_winner() -> None:
    repository = InMemoryCaseRepository()
    service = CaseService(repository, clock=lambda: NOW)
    case = service.create_from_findings(["finding-race"], "rule-v1", 100, "system")

    def attempt(worker_number: int) -> str | None:
        try:
            claimed = service.claim_direct(
                case.case_id,
                case.row_version,
                f"worker-{worker_number}",
                lease_duration=timedelta(minutes=5),
            )
            return claimed.assignee_id
        except CaseConflictError:
            return None

    with ThreadPoolExecutor(max_workers=50) as executor:
        results = list(executor.map(attempt, range(50)))

    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    stored = repository.get_case(case.case_id)
    assert stored.state is CaseState.CLAIMED
    assert stored.assignee_id == winners[0]
    assert stored.row_version == 2


def test_two_worker_heaps_racing_same_database_case_have_one_winner() -> None:
    repository = InMemoryCaseRepository()
    service = CaseService(repository, clock=lambda: NOW)
    case = service.create_from_findings(["finding-two-heaps"], "rule-v1", 95, "system")
    first = CaseWorker(repository, "worker-a", clock=lambda: NOW)
    second = CaseWorker(repository, "worker-b", clock=lambda: NOW)
    assert first.start() == second.start() == 1

    def claim(worker: CaseWorker) -> str:
        try:
            return worker.claim_next(timeout=0).assignee_id or ""
        except ClaimConflictError:
            return "CONFLICT"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, (first, second)))

    assert results.count("CONFLICT") == 1
    assert len([result for result in results if result != "CONFLICT"]) == 1
    assert repository.get_case(case.case_id).row_version == 2
