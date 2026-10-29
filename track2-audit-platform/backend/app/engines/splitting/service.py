"""P11 orchestration from P10 windows to durable splitting findings."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from threading import Lock
from typing import Iterable, Protocol, Sequence
from uuid import NAMESPACE_URL, uuid5

from app.services.finding_service import FindingDraft, StoredFinding

from .partition import (
    DuplicateTransactionConflict,
    PartitionKey,
    SplittingPolicy,
    TransferEvent,
)
from .window import SplittingWindowCandidate, detect_splitting_windows


FINDING_TYPE = "SPLITTING_PATTERN"
ALGORITHM_VERSION = "splitting-v1"


class RunInputConflict(ValueError):
    """Raised when one checkpoint/run key is retried with different input."""


@dataclass(frozen=True, slots=True)
class CandidateCluster:
    partition_key: PartitionKey
    events: tuple[TransferEvent, ...]
    amount_sum_minor: int
    window_start: datetime
    window_end: datetime


@dataclass(frozen=True, slots=True)
class PersistedSplittingRun:
    run_id: str
    run_key: str
    input_digest: str
    checkpoint: str
    policy_version: int
    findings: tuple[StoredFinding, ...]
    status: str = "COMPLETED"


@dataclass(frozen=True, slots=True)
class SplittingRunOutcome:
    run: PersistedSplittingRun
    replayed: bool


class SplittingRunRepository(Protocol):
    """Atomic persistence boundary implemented by the P02 database adapter."""

    def save_completed_run(
        self,
        *,
        run_key: str,
        input_digest: str,
        checkpoint: str,
        policy_version: int,
        findings: Sequence[FindingDraft],
    ) -> SplittingRunOutcome:
        """Atomically persist run, findings, and their associations."""

    def list_findings(
        self,
        *,
        finding_type: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[StoredFinding, ...]:
        """Return a deterministic page of persisted findings."""


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _event_payload(event: TransferEvent) -> dict[str, object]:
    return {
        "transaction_id": event.transaction_id,
        "sender_account_id": event.sender_account_id,
        "receiver_account_id": event.receiver_account_id,
        "amount_minor": event.amount_minor,
        "currency": event.currency,
        "occurred_at": event.occurred_at.isoformat(),
        "transaction_type": event.transaction_type,
        "status": event.status,
        "is_reversal": event.is_reversal,
        "reversal_of_transaction_id": event.reversal_of_transaction_id,
        "is_fee": event.is_fee,
        "is_cash": event.is_cash,
        "is_internal": event.is_internal,
    }


def _policy_payload(policy: SplittingPolicy) -> dict[str, object]:
    return {
        "version": policy.version,
        "window_minutes": policy.window_minutes,
        "amount_threshold_minor": policy.amount_threshold_minor,
        "min_count": policy.min_count,
        "individual_max_minor": policy.individual_max_minor,
        "group_mode": policy.group_mode.value,
        "accepted_statuses": sorted(policy.accepted_statuses),
        "reversal_handling": policy.reversal_handling.value,
        "include_fees": policy.include_fees,
        "include_cash": policy.include_cash,
        "include_internal": policy.include_internal,
        "included_transaction_types": (
            sorted(policy.included_transaction_types)
            if policy.included_transaction_types is not None
            else None
        ),
        "max_window_events": policy.max_window_events,
    }


def _unique_event_map(events: Iterable[TransferEvent]) -> dict[str, TransferEvent]:
    by_id: dict[str, TransferEvent] = {}
    for event in events:
        existing = by_id.get(event.transaction_id)
        if existing is None:
            by_id[event.transaction_id] = event
        elif existing != event:
            raise DuplicateTransactionConflict(
                f"canonical transaction {event.transaction_id!r} has conflicting payloads"
            )
    return by_id


def _input_digest(events: Iterable[TransferEvent], policy: SplittingPolicy) -> str:
    by_id = _unique_event_map(events)
    return _sha256(
        {
            "policy": _policy_payload(policy),
            "events": [_event_payload(by_id[key]) for key in sorted(by_id)],
        }
    )


def _run_key(checkpoint: str, policy: SplittingPolicy) -> str:
    if not checkpoint.strip():
        raise ValueError("checkpoint must not be empty")
    return _sha256(
        {
            "detector": FINDING_TYPE,
            "algorithm_version": ALGORITHM_VERSION,
            "policy_version": policy.version,
            "checkpoint": checkpoint.strip(),
        }
    )


def merge_overlapping_candidates(
    candidates: Sequence[SplittingWindowCandidate],
    events_by_id: dict[str, TransferEvent],
) -> list[CandidateCluster]:
    """Merge transitively overlapping windows within each partition.

    Candidate windows overlap when they share a canonical transaction ID. A
    union-find produces one deterministic cluster for each connected component.
    """

    clusters: list[CandidateCluster] = []
    by_partition: dict[PartitionKey, list[SplittingWindowCandidate]] = {}
    for candidate in candidates:
        by_partition.setdefault(candidate.partition_key, []).append(candidate)

    for partition, partition_candidates in by_partition.items():
        parent: dict[str, str] = {}

        def find(transaction_id: str) -> str:
            parent.setdefault(transaction_id, transaction_id)
            root = transaction_id
            while parent[root] != root:
                root = parent[root]
            while parent[transaction_id] != transaction_id:
                next_id = parent[transaction_id]
                parent[transaction_id] = root
                transaction_id = next_id
            return root

        def union(left: str, right: str) -> None:
            left_root, right_root = find(left), find(right)
            if left_root == right_root:
                return
            if left_root < right_root:
                parent[right_root] = left_root
            else:
                parent[left_root] = right_root

        for candidate in partition_candidates:
            first = candidate.transaction_ids[0]
            find(first)
            for transaction_id in candidate.transaction_ids[1:]:
                union(first, transaction_id)

        grouped_ids: dict[str, list[str]] = {}
        for transaction_id in parent:
            if transaction_id not in events_by_id:
                raise ValueError(f"candidate references unknown transaction {transaction_id!r}")
            grouped_ids.setdefault(find(transaction_id), []).append(transaction_id)

        for transaction_ids in grouped_ids.values():
            ordered_events = tuple(
                sorted(
                    (events_by_id[transaction_id] for transaction_id in transaction_ids),
                    key=lambda event: (event.occurred_at, event.transaction_id),
                )
            )
            clusters.append(
                CandidateCluster(
                    partition_key=partition,
                    events=ordered_events,
                    amount_sum_minor=sum(event.amount_minor for event in ordered_events),
                    window_start=ordered_events[0].occurred_at,
                    window_end=ordered_events[-1].occurred_at,
                )
            )

    clusters.sort(
        key=lambda cluster: (
            cluster.window_start,
            cluster.window_end,
            repr(cluster.partition_key),
            tuple(event.transaction_id for event in cluster.events),
        )
    )
    return clusters


def _finding_fingerprint(cluster: CandidateCluster, policy: SplittingPolicy) -> str:
    return _sha256(
        {
            "finding_type": FINDING_TYPE,
            "algorithm_version": ALGORITHM_VERSION,
            "policy_version": policy.version,
            "partition_key": asdict(cluster.partition_key),
            "transaction_ids": [event.transaction_id for event in cluster.events],
        }
    )


def cluster_to_finding(
    cluster: CandidateCluster,
    policy: SplittingPolicy,
    checkpoint: str,
) -> FindingDraft:
    duration_minutes = int(
        (cluster.window_end - cluster.window_start).total_seconds() // 60
    )
    transaction_ids = tuple(event.transaction_id for event in cluster.events)
    return FindingDraft(
        finding_type=FINDING_TYPE,
        fingerprint=_finding_fingerprint(cluster, policy),
        transaction_ids=transaction_ids,
        config_version=policy.version,
        algorithm_version=ALGORITHM_VERSION,
        facts={
            "Splitting_Window_Sum_Minor": cluster.amount_sum_minor,
            "Splitting_Window_Count": len(cluster.events),
            "Splitting_Window_Duration_Minutes": duration_minutes,
            "Splitting_Threshold_Minor": policy.amount_threshold_minor,
            "Transaction_Velocity": len(cluster.events),
        },
        evidence={
            "partition_key": asdict(cluster.partition_key),
            "window_start": cluster.window_start.isoformat(),
            "window_end": cluster.window_end.isoformat(),
            "source_checkpoint": checkpoint,
            "policy": _policy_payload(policy),
            "transactions": [
                {
                    "transaction_id": event.transaction_id,
                    "amount_minor": event.amount_minor,
                    "occurred_at": event.occurred_at.isoformat(),
                }
                for event in cluster.events
            ],
        },
    )


def run_splitting_detector(
    events: Iterable[TransferEvent],
    policy: SplittingPolicy,
    checkpoint: str,
    repository: SplittingRunRepository,
) -> SplittingRunOutcome:
    """Run P10, merge overlaps, and atomically persist an idempotent P11 run."""

    event_list = list(events)
    events_by_id = _unique_event_map(event_list)
    candidates = detect_splitting_windows(event_list, policy)
    clusters = merge_overlapping_candidates(candidates, events_by_id)
    findings = [cluster_to_finding(cluster, policy, checkpoint) for cluster in clusters]
    return repository.save_completed_run(
        run_key=_run_key(checkpoint, policy),
        input_digest=_input_digest(event_list, policy),
        checkpoint=checkpoint.strip(),
        policy_version=policy.version,
        findings=findings,
    )


class InMemorySplittingRunRepository:
    """Thread-safe transactional test adapter for the persistence port."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._runs: dict[str, PersistedSplittingRun] = {}
        self._findings: dict[str, StoredFinding] = {}

    @property
    def run_count(self) -> int:
        with self._lock:
            return len(self._runs)

    @property
    def finding_count(self) -> int:
        with self._lock:
            return len(self._findings)

    def save_completed_run(
        self,
        *,
        run_key: str,
        input_digest: str,
        checkpoint: str,
        policy_version: int,
        findings: Sequence[FindingDraft],
    ) -> SplittingRunOutcome:
        with self._lock:
            existing_run = self._runs.get(run_key)
            if existing_run is not None:
                if existing_run.input_digest != input_digest:
                    raise RunInputConflict(
                        "the detector checkpoint was already completed with different input"
                    )
                return SplittingRunOutcome(existing_run, replayed=True)

            if len({finding.fingerprint for finding in findings}) != len(findings):
                raise ValueError("a run cannot contain duplicate finding fingerprints")

            stored_findings: list[StoredFinding] = []
            pending_findings = dict(self._findings)
            for draft in findings:
                stored = pending_findings.get(draft.fingerprint)
                if stored is None:
                    finding_id = str(uuid5(NAMESPACE_URL, f"finding:{draft.fingerprint}"))
                    stored = StoredFinding(finding_id=finding_id, draft=draft)
                    pending_findings[draft.fingerprint] = stored
                stored_findings.append(stored)

            run_id = str(uuid5(NAMESPACE_URL, f"splitting-run:{run_key}"))
            run = PersistedSplittingRun(
                run_id=run_id,
                run_key=run_key,
                input_digest=input_digest,
                checkpoint=checkpoint,
                policy_version=policy_version,
                findings=tuple(stored_findings),
            )
            self._findings = pending_findings
            self._runs[run_key] = run
            return SplittingRunOutcome(run, replayed=False)

    def list_findings(
        self,
        *,
        finding_type: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[StoredFinding, ...]:
        if offset < 0:
            raise ValueError("offset must not be negative")
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        with self._lock:
            values = sorted(
                self._findings.values(),
                key=lambda finding: (finding.draft.fingerprint, finding.finding_id),
            )
            if finding_type is not None:
                values = [
                    finding
                    for finding in values
                    if finding.draft.finding_type == finding_type
                ]
            return tuple(values[offset : offset + limit])
