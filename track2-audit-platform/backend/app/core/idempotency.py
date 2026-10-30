"""Shared idempotency-key and deterministic payload identity rules."""

from __future__ import annotations

import re

from app.schemas.common import deterministic_fingerprint


_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")


def normalize_idempotency_key(value: str) -> str:
    key = value.strip()
    if not _KEY_PATTERN.fullmatch(key):
        raise ValueError(
            "idempotency key must be 8-128 safe ASCII characters"
        )
    return key


def idempotency_payload_hash(operation: str, payload: object) -> str:
    return deterministic_fingerprint(f"idempotency:{operation}", payload)
