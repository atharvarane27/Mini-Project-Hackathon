"""Bounded Levenshtein edit-distance for duplicate classification.

The implementation uses the classic Wagner-Fischer dynamic-programming approach
with a two-row memory optimisation. It also normalises text before comparing so
that case and whitespace differences do not distort the scoring.
"""

from __future__ import annotations

from typing import Any


def normalize_text(value: Any) -> str:
    """Lowercase and compact text so comparisons are deterministic."""
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = "".join(ch for ch in text if ch.isalnum() or ch.isspace())
    return " ".join(text.split())


def levenshtein_distance(a: str, b: str, *, max_distance: int | None = None) -> int:
    """Return the minimum edit distance between two strings.

    The implementation keeps only two rows in memory for O(min(len(a), len(b)))
    space while still performing the standard edit-distance computation.
    """
    a = normalize_text(a)
    b = normalize_text(b)

    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    if len(a) > len(b):
        a, b = b, a

    if max_distance is not None:
        # If the strings differ by more than the limit, we can early-stop.
        if abs(len(b) - len(a)) > max_distance:
            return max_distance + 1

    prev = list(range(len(b) + 1))
    curr = [0] * (len(b) + 1)

    for i in range(1, len(a) + 1):
        curr[0] = i
        row_min = i
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(
                prev[j] + 1,
                curr[j - 1] + 1,
                prev[j - 1] + cost,
            )
            row_min = min(row_min, curr[j])
        if max_distance is not None and row_min > max_distance:
            return max_distance + 1
        prev, curr = curr, prev

    return prev[len(b)]


def levenshtein_similarity(a: str, b: str) -> float:
    """Return a normalized similarity score in the range [0.0, 1.0]."""
    a = normalize_text(a)
    b = normalize_text(b)

    if a == b:
        return 1.0
    if not a and not b:
        return 1.0

    max_len = max(len(a), len(b))
    if max_len == 0:
        return 1.0

    dist = levenshtein_distance(a, b)
    return 1.0 - (dist / max_len)
