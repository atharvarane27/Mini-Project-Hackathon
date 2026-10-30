"""Deterministic exact-financial and phonetic blocking keys."""

from __future__ import annotations

from dataclasses import dataclass

from .levenshtein import normalize_identity_text
from .resolver import IdentityRecord
from .soundex import soundex


@dataclass(frozen=True, slots=True)
class BlockingPolicy:
    amount_band_minor: int = 100_000
    max_bucket_size: int = 500

    def __post_init__(self) -> None:
        if self.amount_band_minor <= 0 or self.max_bucket_size <= 0:
            raise ValueError("blocking policy bounds must be positive")


def blocking_keys(
    record: IdentityRecord,
    policy: BlockingPolicy | None = None,
) -> tuple[str, ...]:
    configured = policy or BlockingPolicy()
    day = record.occurred_at.date().isoformat()
    band = record.amount_minor // configured.amount_band_minor
    reference = normalize_identity_text(record.transaction_reference).replace(" ", "")
    keys = {
        f"ref:{reference}",
        f"sender:{record.sender_account_id}|{day}|{band}|{record.currency}",
        f"receiver:{record.receiver_account_id}|{day}|{band}|{record.currency}",
        f"financial:{day}|{band}|{record.currency}",
        f"phonetic:{soundex(record.sender_name)}|{soundex(record.receiver_name)}|{record.currency}",
    }
    return tuple(sorted(keys))
