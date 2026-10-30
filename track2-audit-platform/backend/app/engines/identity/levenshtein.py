"""Unicode normalization and custom bounded Levenshtein distance."""

from __future__ import annotations

import re
import unicodedata


_SEPARATORS = re.compile(r"[^\w]+", flags=re.UNICODE)


def normalize_identity_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return " ".join(_SEPARATORS.sub(" ", normalized).split())


def bounded_levenshtein(left: str, right: str, max_distance: int) -> int | None:
    if max_distance < 0:
        raise ValueError("max_distance must not be negative")
    left_value = normalize_identity_text(left)
    right_value = normalize_identity_text(right)
    if left_value == right_value:
        return 0
    if abs(len(left_value) - len(right_value)) > max_distance:
        return None
    if len(left_value) > len(right_value):
        left_value, right_value = right_value, left_value
    previous = list(range(len(left_value) + 1))
    for right_index, right_character in enumerate(right_value, start=1):
        current = [right_index]
        row_minimum = right_index
        for left_index, left_character in enumerate(left_value, start=1):
            value = min(
                current[-1] + 1,
                previous[left_index] + 1,
                previous[left_index - 1]
                + int(left_character != right_character),
            )
            current.append(value)
            row_minimum = min(row_minimum, value)
        if row_minimum > max_distance:
            return None
        previous = current
    distance = previous[-1]
    return distance if distance <= max_distance else None
