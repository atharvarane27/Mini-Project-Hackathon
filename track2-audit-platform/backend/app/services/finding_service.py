"""Shared immutable finding contracts used by detector engines.

Persistence adapters may translate these contracts to the P02 SQLAlchemy
models. Detector engines must not write database rows directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True, slots=True)
class FindingDraft:
    """Canonical detector output before persistence assigns an ID."""

    finding_type: str
    fingerprint: str
    transaction_ids: tuple[str, ...]
    facts: Mapping[str, object]
    evidence: Mapping[str, object]
    config_version: int
    algorithm_version: str
    status: str = "FLAGGED_FOR_REVIEW"

    def __post_init__(self) -> None:
        if not self.finding_type.strip():
            raise ValueError("finding_type must not be empty")
        if len(self.fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in self.fingerprint
        ):
            raise ValueError("fingerprint must be a lowercase SHA-256 hex digest")
        if not self.transaction_ids or len(set(self.transaction_ids)) != len(
            self.transaction_ids
        ):
            raise ValueError("transaction_ids must be non-empty and unique")
        if self.config_version <= 0:
            raise ValueError("config_version must be positive")
        if not self.algorithm_version.strip():
            raise ValueError("algorithm_version must not be empty")


@dataclass(frozen=True, slots=True)
class StoredFinding:
    """Finding identity plus its immutable detector draft."""

    finding_id: str
    draft: FindingDraft

    def as_dict(self) -> dict[str, object]:
        return {
            "finding_id": self.finding_id,
            "type": self.draft.finding_type,
            "status": self.draft.status,
            "algorithm_version": self.draft.algorithm_version,
            "detector_config_version": self.draft.config_version,
            "transaction_ids": list(self.draft.transaction_ids),
            "facts": dict(self.draft.facts),
            "evidence": dict(self.draft.evidence),
            "fingerprint": self.draft.fingerprint,
        }
