"""Idempotent circular-flow validation, findings, and detector runs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from threading import Lock
from typing import Iterable, Protocol, Sequence
from uuid import NAMESPACE_URL, uuid5

from app.services.finding_service import FindingDraft, StoredFinding

from .temporal_validator import CircularPolicy, CycleCandidate, ValidatedCycle, validate_cycle


FINDING_TYPE = "CIRCULAR_FLOW"
ALGORITHM_VERSION = "circular-temporal-v1"


class CircularRunInputConflict(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PersistedCircularRun:
    run_id: str
    run_key: str
    input_digest: str
    checkpoint: str
    policy_version: int
    findings: tuple[StoredFinding, ...]
    status: str = "COMPLETED"


@dataclass(frozen=True, slots=True)
class CircularRunOutcome:
    run: PersistedCircularRun
    replayed: bool


class CircularRunRepository(Protocol):
    def save_completed_run(
        self,
        *,
        run_key: str,
        input_digest: str,
        checkpoint: str,
        policy_version: int,
        findings: Sequence[FindingDraft],
    ) -> CircularRunOutcome: ...

    def list_findings(
        self,
        *,
        finding_type: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[StoredFinding, ...]: ...


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: object) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def _policy_payload(policy: CircularPolicy) -> dict[str, int]:
    return {
        "version": policy.version,
        "window_minutes": policy.window_minutes,
        "min_path_length": policy.min_path_length,
        "max_path_length": policy.max_path_length,
        "min_initial_amount_minor": policy.min_initial_amount_minor,
        "max_amount_variation_bps": policy.max_amount_variation_bps,
    }


def _candidate_payload(candidate: CycleCandidate) -> dict[str, object]:
    return {
        "account_path": candidate.account_path,
        "transfers": [
            {
                "transaction_id": transfer.transaction_id,
                "sender": transfer.sender_account_id,
                "receiver": transfer.receiver_account_id,
                "amount_minor": transfer.amount_minor,
                "currency": transfer.currency,
                "occurred_at": transfer.occurred_at.isoformat(),
            }
            for transfer in candidate.transfers
        ],
    }


def _unique_candidates(candidates: Iterable[CycleCandidate]) -> list[CycleCandidate]:
    unique: dict[str, CycleCandidate] = {}
    for candidate in candidates:
        payload = _candidate_payload(candidate)
        unique.setdefault(_digest(payload), candidate)
    return [unique[key] for key in sorted(unique)]


def _finding(cycle: ValidatedCycle, policy: CircularPolicy, checkpoint: str) -> FindingDraft:
    transaction_ids = tuple(item.transaction_id for item in cycle.transfers)
    fingerprint = _digest(
        {
            "type": FINDING_TYPE,
            "algorithm": ALGORITHM_VERSION,
            "policy_version": policy.version,
            "account_path": cycle.account_path,
            "transaction_ids": transaction_ids,
        }
    )
    return FindingDraft(
        finding_type=FINDING_TYPE,
        fingerprint=fingerprint,
        transaction_ids=transaction_ids,
        config_version=policy.version,
        algorithm_version=ALGORITHM_VERSION,
        facts={
            "Circular_Flow_Detected": True,
            "Cycle_Length": len(cycle.transfers),
            "Cycle_Duration_Minutes": int(cycle.duration.total_seconds() // 60),
            "Initial_Amount_Minor": cycle.initial_amount_minor,
            "Minimum_Amount_Minor": cycle.minimum_amount_minor,
            "Maximum_Amount_Minor": cycle.maximum_amount_minor,
        },
        evidence={
            "account_path": list(cycle.account_path),
            "ordered_transaction_ids": list(transaction_ids),
            "source_checkpoint": checkpoint,
            "policy": _policy_payload(policy),
            "transfers": [
                {
                    "transaction_id": item.transaction_id,
                    "sender_account_id": item.sender_account_id,
                    "receiver_account_id": item.receiver_account_id,
                    "amount_minor": item.amount_minor,
                    "currency": item.currency,
                    "occurred_at": item.occurred_at.isoformat(),
                }
                for item in cycle.transfers
            ],
        },
    )


def run_circular_detector(
    candidates: Iterable[CycleCandidate],
    policy: CircularPolicy,
    checkpoint: str,
    repository: CircularRunRepository,
) -> CircularRunOutcome:
    normalized_checkpoint = checkpoint.strip()
    if not normalized_checkpoint:
        raise ValueError("checkpoint must not be empty")
    unique = _unique_candidates(candidates)
    detected = [
        _finding(validated, policy, normalized_checkpoint)
        for candidate in unique
        if (validated := validate_cycle(candidate, policy)) is not None
    ]
    findings = list(
        {
            finding.fingerprint: finding
            for finding in detected
        }.values()
    )
    run_key = _digest(
        {
            "type": FINDING_TYPE,
            "algorithm": ALGORITHM_VERSION,
            "policy_version": policy.version,
            "checkpoint": normalized_checkpoint,
        }
    )
    input_digest = _digest(
        {
            "policy": _policy_payload(policy),
            "candidates": sorted(
                (_candidate_payload(candidate) for candidate in unique),
                key=_json,
            ),
        }
    )
    return repository.save_completed_run(
        run_key=run_key,
        input_digest=input_digest,
        checkpoint=normalized_checkpoint,
        policy_version=policy.version,
        findings=findings,
    )


class InMemoryCircularRunRepository:
    def __init__(self) -> None:
        self._lock = Lock()
        self._runs: dict[str, PersistedCircularRun] = {}
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
    ) -> CircularRunOutcome:
        with self._lock:
            existing = self._runs.get(run_key)
            if existing is not None:
                if existing.input_digest != input_digest:
                    raise CircularRunInputConflict(
                        "checkpoint already completed with different circular input"
                    )
                return CircularRunOutcome(existing, True)
            pending = dict(self._findings)
            stored: list[StoredFinding] = []
            for draft in findings:
                item = pending.get(draft.fingerprint)
                if item is None:
                    item = StoredFinding(
                        str(uuid5(NAMESPACE_URL, f"finding:{draft.fingerprint}")), draft
                    )
                    pending[draft.fingerprint] = item
                stored.append(item)
            run = PersistedCircularRun(
                str(uuid5(NAMESPACE_URL, f"circular-run:{run_key}")),
                run_key,
                input_digest,
                checkpoint,
                policy_version,
                tuple(stored),
            )
            self._findings = pending
            self._runs[run_key] = run
            return CircularRunOutcome(run, False)

    def list_findings(
        self,
        *,
        finding_type: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[StoredFinding, ...]:
        if offset < 0 or not 1 <= limit <= 500:
            raise ValueError("invalid finding page")
        with self._lock:
            values = sorted(
                self._findings.values(), key=lambda item: item.draft.fingerprint
            )
            if finding_type is not None:
                values = [
                    item for item in values if item.draft.finding_type == finding_type
                ]
            return tuple(values[offset : offset + limit])
