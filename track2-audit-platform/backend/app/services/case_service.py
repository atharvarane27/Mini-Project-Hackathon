"""Case lifecycle contracts and a transactionally faithful in-memory adapter.

The repository protocol is the seam for the P02 Supabase/PostgreSQL adapter.
The in-memory adapter deliberately models the same atomic and compare-and-swap
semantics so orchestration can be verified before that branch is merged.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from threading import Lock
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5


class CaseState(StrEnum):
    QUEUED = "QUEUED"
    CLAIMED = "CLAIMED"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"


class OutboxState(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    PUBLISHED = "PUBLISHED"
    DEAD_LETTER = "DEAD_LETTER"


class CaseNotFoundError(KeyError):
    pass


class CaseConflictError(RuntimeError):
    pass


class InvalidCaseTransitionError(ValueError):
    pass


class AtomicCommitError(RuntimeError):
    """Injected failure used to prove no partial transaction is observable."""


@dataclass(frozen=True, slots=True)
class AuditCase:
    case_id: str
    case_code: str
    stable_key: str
    finding_ids: tuple[str, ...]
    rule_version_id: str
    priority: int
    state: CaseState
    row_version: int
    assignee_id: str | None
    lease_until: datetime | None
    created_at: datetime
    updated_at: datetime

    def as_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "case_code": self.case_code,
            "stable_key": self.stable_key,
            "finding_ids": list(self.finding_ids),
            "rule_version_id": self.rule_version_id,
            "priority": self.priority,
            "state": self.state.value,
            "row_version": self.row_version,
            "assignee_id": self.assignee_id,
            "lease_until": self.lease_until.isoformat() if self.lease_until else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    event_id: str
    event_type: str
    entity_id: str
    entity_version: int
    payload: Mapping[str, object]
    status: OutboxState
    attempt_count: int
    available_at: datetime
    created_at: datetime
    claim_owner: str | None = None
    claimed_until: datetime | None = None
    last_error: str | None = None


@dataclass(frozen=True, slots=True)
class AuditIntent:
    intent_id: str
    object_id: str
    action: str
    actor_id: str
    object_version: int
    occurred_at: datetime
    details: Mapping[str, object]


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(UTC)


def stable_case_key(finding_ids: Sequence[str], rule_version_id: str) -> str:
    normalized_findings = tuple(
        sorted({value.strip() for value in finding_ids if value.strip()})
    )
    normalized_rule = rule_version_id.strip()
    if not normalized_findings:
        raise ValueError("at least one finding ID is required")
    if not normalized_rule:
        raise ValueError("rule_version_id must not be empty")
    payload = json.dumps(
        {"finding_ids": normalized_findings, "rule_version_id": normalized_rule},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class CaseRepository(Protocol):
    def create_case_bundle(
        self,
        *,
        stable_key: str,
        finding_ids: tuple[str, ...],
        rule_version_id: str,
        priority: int,
        actor_id: str,
        now: datetime,
    ) -> AuditCase: ...

    def get_case(self, case_id: str) -> AuditCase: ...

    def list_cases(self) -> tuple[AuditCase, ...]: ...

    def list_recoverable_cases(self) -> tuple[AuditCase, ...]: ...

    def compare_and_swap_claim(
        self,
        *,
        case_id: str,
        expected_version: int,
        worker_id: str,
        now: datetime,
        lease_until: datetime,
    ) -> AuditCase | None: ...

    def compare_and_swap_transition(
        self,
        *,
        case_id: str,
        expected_version: int,
        new_state: CaseState,
        actor_id: str,
        now: datetime,
    ) -> AuditCase | None: ...

    def recover_expired_leases(self, *, now: datetime) -> tuple[AuditCase, ...]: ...

    def claim_outbox_events(
        self,
        *,
        worker_id: str,
        now: datetime,
        claimed_until: datetime,
        limit: int,
    ) -> tuple[OutboxEvent, ...]: ...

    def complete_outbox_event(self, event_id: str, worker_id: str) -> bool: ...

    def fail_outbox_event(
        self,
        *,
        event_id: str,
        worker_id: str,
        error: str,
        retry_at: datetime,
        max_attempts: int,
    ) -> OutboxEvent | None: ...


_ALLOWED_TRANSITIONS: Mapping[CaseState, frozenset[CaseState]] = {
    CaseState.CLAIMED: frozenset({CaseState.IN_PROGRESS}),
    CaseState.IN_PROGRESS: frozenset({CaseState.RESOLVED, CaseState.REJECTED}),
    CaseState.RESOLVED: frozenset({CaseState.CLOSED}),
    CaseState.REJECTED: frozenset({CaseState.CLOSED}),
}


class InMemoryCaseRepository:
    """Thread-safe reference adapter for the future PostgreSQL transaction API."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._cases: dict[str, AuditCase] = {}
        self._case_ids_by_key: dict[str, str] = {}
        self._outbox: dict[str, OutboxEvent] = {}
        self._audit_intents: list[AuditIntent] = []
        self._fail_next_commit = False

    def inject_commit_failure_once(self) -> None:
        with self._lock:
            self._fail_next_commit = True

    def _event_for_case(self, case: AuditCase, now: datetime) -> OutboxEvent:
        event_id = str(
            uuid5(NAMESPACE_URL, f"case-queued:{case.case_id}:{case.row_version}")
        )
        return OutboxEvent(
            event_id=event_id,
            event_type="CASE_QUEUED",
            entity_id=case.case_id,
            entity_version=case.row_version,
            payload={
                "case_id": case.case_id,
                "priority": case.priority,
                "row_version": case.row_version,
            },
            status=OutboxState.PENDING,
            attempt_count=0,
            available_at=now,
            created_at=now,
        )

    def _audit(
        self,
        case: AuditCase,
        action: str,
        actor_id: str,
        now: datetime,
        details: Mapping[str, object],
    ) -> AuditIntent:
        return AuditIntent(
            intent_id=str(
                uuid5(
                    NAMESPACE_URL,
                    f"audit:{case.case_id}:{case.row_version}:{action}",
                )
            ),
            object_id=case.case_id,
            action=action,
            actor_id=actor_id,
            object_version=case.row_version,
            occurred_at=now,
            details=dict(details),
        )

    def create_case_bundle(
        self,
        *,
        stable_key: str,
        finding_ids: tuple[str, ...],
        rule_version_id: str,
        priority: int,
        actor_id: str,
        now: datetime,
    ) -> AuditCase:
        with self._lock:
            existing_id = self._case_ids_by_key.get(stable_key)
            if existing_id is not None:
                return self._cases[existing_id]
            if self._fail_next_commit:
                self._fail_next_commit = False
                raise AtomicCommitError("simulated atomic commit failure")

            case_id = str(uuid5(NAMESPACE_URL, f"audit-case:{stable_key}"))
            case = AuditCase(
                case_id=case_id,
                case_code=f"CASE-{stable_key[:12].upper()}",
                stable_key=stable_key,
                finding_ids=finding_ids,
                rule_version_id=rule_version_id,
                priority=priority,
                state=CaseState.QUEUED,
                row_version=1,
                assignee_id=None,
                lease_until=None,
                created_at=now,
                updated_at=now,
            )
            event = self._event_for_case(case, now)
            intent = self._audit(case, "CASE_CREATED", actor_id, now, {})
            self._cases[case_id] = case
            self._case_ids_by_key[stable_key] = case_id
            self._outbox[event.event_id] = event
            self._audit_intents.append(intent)
            return case

    def get_case(self, case_id: str) -> AuditCase:
        with self._lock:
            try:
                return self._cases[case_id]
            except KeyError as error:
                raise CaseNotFoundError(f"case {case_id!r} was not found") from error

    def list_cases(self) -> tuple[AuditCase, ...]:
        with self._lock:
            return tuple(
                sorted(
                    self._cases.values(),
                    key=lambda case: (case.created_at, case.case_id),
                )
            )

    def list_recoverable_cases(self) -> tuple[AuditCase, ...]:
        with self._lock:
            return tuple(
                sorted(
                    (
                        case
                        for case in self._cases.values()
                        if case.state is CaseState.QUEUED
                    ),
                    key=lambda case: (-case.priority, case.created_at, case.case_id),
                )
            )

    def compare_and_swap_claim(
        self,
        *,
        case_id: str,
        expected_version: int,
        worker_id: str,
        now: datetime,
        lease_until: datetime,
    ) -> AuditCase | None:
        with self._lock:
            current = self._cases.get(case_id)
            if (
                current is None
                or current.state is not CaseState.QUEUED
                or current.row_version != expected_version
            ):
                return None
            claimed = replace(
                current,
                state=CaseState.CLAIMED,
                row_version=current.row_version + 1,
                assignee_id=worker_id,
                lease_until=lease_until,
                updated_at=now,
            )
            self._cases[case_id] = claimed
            self._audit_intents.append(
                self._audit(claimed, "CASE_CLAIMED", worker_id, now, {})
            )
            return claimed

    def compare_and_swap_transition(
        self,
        *,
        case_id: str,
        expected_version: int,
        new_state: CaseState,
        actor_id: str,
        now: datetime,
    ) -> AuditCase | None:
        with self._lock:
            current = self._cases.get(case_id)
            if current is None:
                raise CaseNotFoundError(f"case {case_id!r} was not found")
            if current.row_version != expected_version:
                return None
            if new_state not in _ALLOWED_TRANSITIONS.get(current.state, frozenset()):
                raise InvalidCaseTransitionError(
                    f"cannot transition case from {current.state.value} "
                    f"to {new_state.value}"
                )
            terminal = new_state in {
                CaseState.RESOLVED,
                CaseState.REJECTED,
                CaseState.CLOSED,
            }
            transitioned = replace(
                current,
                state=new_state,
                row_version=current.row_version + 1,
                assignee_id=None if terminal else current.assignee_id,
                lease_until=None if terminal else current.lease_until,
                updated_at=now,
            )
            self._cases[case_id] = transitioned
            self._audit_intents.append(
                self._audit(
                    transitioned,
                    "CASE_TRANSITIONED",
                    actor_id,
                    now,
                    {"old_state": current.state.value, "new_state": new_state.value},
                )
            )
            return transitioned

    def recover_expired_leases(self, *, now: datetime) -> tuple[AuditCase, ...]:
        recovered: list[AuditCase] = []
        with self._lock:
            for case_id, current in tuple(self._cases.items()):
                if (
                    current.state not in {CaseState.CLAIMED, CaseState.IN_PROGRESS}
                    or current.lease_until is None
                    or current.lease_until > now
                ):
                    continue
                queued = replace(
                    current,
                    state=CaseState.QUEUED,
                    row_version=current.row_version + 1,
                    assignee_id=None,
                    lease_until=None,
                    updated_at=now,
                )
                event = self._event_for_case(queued, now)
                self._cases[case_id] = queued
                self._outbox.setdefault(event.event_id, event)
                self._audit_intents.append(
                    self._audit(queued, "CASE_LEASE_EXPIRED", "SYSTEM", now, {})
                )
                recovered.append(queued)
        return tuple(recovered)

    def claim_outbox_events(
        self,
        *,
        worker_id: str,
        now: datetime,
        claimed_until: datetime,
        limit: int,
    ) -> tuple[OutboxEvent, ...]:
        claimed: list[OutboxEvent] = []
        with self._lock:
            candidates = sorted(
                self._outbox.values(),
                key=lambda event: (event.created_at, event.event_id),
            )
            for event in candidates:
                pending = (
                    event.status is OutboxState.PENDING
                    and event.available_at <= now
                )
                abandoned = (
                    event.status is OutboxState.PROCESSING
                    and event.claimed_until is not None
                    and event.claimed_until <= now
                )
                if not (pending or abandoned):
                    continue
                updated = replace(
                    event,
                    status=OutboxState.PROCESSING,
                    attempt_count=event.attempt_count + 1,
                    claim_owner=worker_id,
                    claimed_until=claimed_until,
                )
                self._outbox[event.event_id] = updated
                claimed.append(updated)
                if len(claimed) == limit:
                    break
        return tuple(claimed)

    def complete_outbox_event(self, event_id: str, worker_id: str) -> bool:
        with self._lock:
            event = self._outbox.get(event_id)
            if (
                event is None
                or event.status is not OutboxState.PROCESSING
                or event.claim_owner != worker_id
            ):
                return False
            self._outbox[event_id] = replace(
                event,
                status=OutboxState.PUBLISHED,
                claim_owner=None,
                claimed_until=None,
                last_error=None,
            )
            return True

    def fail_outbox_event(
        self,
        *,
        event_id: str,
        worker_id: str,
        error: str,
        retry_at: datetime,
        max_attempts: int,
    ) -> OutboxEvent | None:
        with self._lock:
            event = self._outbox.get(event_id)
            if (
                event is None
                or event.status is not OutboxState.PROCESSING
                or event.claim_owner != worker_id
            ):
                return None
            dead = event.attempt_count >= max_attempts
            updated = replace(
                event,
                status=OutboxState.DEAD_LETTER if dead else OutboxState.PENDING,
                available_at=retry_at,
                claim_owner=None,
                claimed_until=None,
                last_error=error,
            )
            self._outbox[event_id] = updated
            return updated

    def list_outbox_events(self) -> tuple[OutboxEvent, ...]:
        with self._lock:
            return tuple(
                sorted(
                    self._outbox.values(),
                    key=lambda event: (event.created_at, event.event_id),
                )
            )

    def list_audit_intents(self) -> tuple[AuditIntent, ...]:
        with self._lock:
            return tuple(self._audit_intents)


class CaseService:
    def __init__(
        self,
        repository: CaseRepository,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.clock = clock or (lambda: datetime.now(UTC))

    def _now(self) -> datetime:
        return _utc(self.clock(), "case service clock")

    def create_from_findings(
        self,
        finding_ids: Sequence[str],
        rule_version_id: str,
        priority: int,
        actor_id: str,
    ) -> AuditCase:
        if (
            isinstance(priority, bool)
            or not isinstance(priority, int)
            or not 0 <= priority <= 100
        ):
            raise ValueError("priority must be an integer from 0 to 100")
        normalized_actor = actor_id.strip()
        if not normalized_actor:
            raise ValueError("actor_id must not be empty")
        normalized_findings = tuple(
            sorted({value.strip() for value in finding_ids if value.strip()})
        )
        key = stable_case_key(normalized_findings, rule_version_id)
        return self.repository.create_case_bundle(
            stable_key=key,
            finding_ids=normalized_findings,
            rule_version_id=rule_version_id.strip(),
            priority=priority,
            actor_id=normalized_actor,
            now=self._now(),
        )

    def list_cases(self) -> tuple[AuditCase, ...]:
        return self.repository.list_cases()

    def get(self, case_id: str) -> AuditCase:
        return self.repository.get_case(case_id)

    def transition(
        self,
        case_id: str,
        expected_version: int,
        new_state: CaseState,
        actor_id: str,
    ) -> AuditCase:
        if expected_version <= 0:
            raise ValueError("expected_version must be positive")
        actor = actor_id.strip()
        if not actor:
            raise ValueError("actor_id must not be empty")
        result = self.repository.compare_and_swap_transition(
            case_id=case_id,
            expected_version=expected_version,
            new_state=new_state,
            actor_id=actor,
            now=self._now(),
        )
        if result is None:
            raise CaseConflictError("case row version changed before transition")
        return result

    def recover_expired_leases(self) -> tuple[AuditCase, ...]:
        return self.repository.recover_expired_leases(now=self._now())

    def claim_direct(
        self,
        case_id: str,
        expected_version: int,
        worker_id: str,
        lease_duration: timedelta,
    ) -> AuditCase:
        if lease_duration <= timedelta(0):
            raise ValueError("lease_duration must be positive")
        now = self._now()
        worker = worker_id.strip()
        if not worker:
            raise ValueError("worker_id must not be empty")
        result = self.repository.compare_and_swap_claim(
            case_id=case_id,
            expected_version=expected_version,
            worker_id=worker,
            now=now,
            lease_until=now + lease_duration,
        )
        if result is None:
            self.repository.get_case(case_id)
            raise CaseConflictError(
                "case was already claimed or its row version changed"
            )
        return result
