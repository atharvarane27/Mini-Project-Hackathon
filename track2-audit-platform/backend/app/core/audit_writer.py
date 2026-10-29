"""Append-only activity ledger with optional chained-hash verification."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Mapping
from uuid import uuid4


class ActivityMutationError(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class ActivityEntry:
    activity_id: str
    actor_id: str
    action: str
    object_id: str
    object_version: int
    occurred_at: datetime
    request_id: str
    old_values: Mapping[str, object]
    new_values: Mapping[str, object]
    previous_hash: str
    entry_hash: str

    def as_dict(self) -> dict[str, object]:
        return {
            "activity_id": self.activity_id, "actor_id": self.actor_id,
            "action": self.action, "object_id": self.object_id,
            "object_version": self.object_version,
            "occurred_at": self.occurred_at.isoformat(), "request_id": self.request_id,
            "old_values": dict(self.old_values), "new_values": dict(self.new_values),
            "previous_hash": self.previous_hash, "entry_hash": self.entry_hash,
        }


class ActivityLedger:
    def __init__(self) -> None:
        self._lock = Lock()
        self._entries: list[ActivityEntry] = []

    @staticmethod
    def _digest(payload: Mapping[str, object]) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode()).hexdigest()

    def append(
        self, *, actor_id: str, action: str, object_id: str, object_version: int,
        occurred_at: datetime, request_id: str, old_values: Mapping[str, object],
        new_values: Mapping[str, object],
    ) -> ActivityEntry:
        with self._lock:
            previous = self._entries[-1].entry_hash if self._entries else "0" * 64
            activity_id = str(uuid4())
            payload = {
                "activity_id": activity_id, "actor_id": actor_id, "action": action,
                "object_id": object_id, "object_version": object_version,
                "occurred_at": occurred_at.isoformat(), "request_id": request_id,
                "old_values": dict(old_values), "new_values": dict(new_values),
                "previous_hash": previous,
            }
            entry = ActivityEntry(
                activity_id, actor_id, action, object_id, object_version, occurred_at,
                request_id, dict(old_values), dict(new_values), previous,
                self._digest(payload),
            )
            self._entries.append(entry)
            return entry

    def list(self) -> tuple[ActivityEntry, ...]:
        with self._lock:
            return tuple(self._entries)

    def verify(self) -> bool:
        entries = self.list()
        previous = "0" * 64
        for entry in entries:
            payload = entry.as_dict()
            digest = payload.pop("entry_hash")
            if entry.previous_hash != previous or self._digest(payload) != digest:
                return False
            previous = entry.entry_hash
        return True

    def update(self, *_: object, **__: object) -> None:
        raise ActivityMutationError("activity ledger is append-only")

    def delete(self, *_: object, **__: object) -> None:
        raise ActivityMutationError("activity ledger is append-only")
