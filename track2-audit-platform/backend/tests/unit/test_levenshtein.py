"""P06 custom normalization and bounded edit-distance tests."""

import pytest

from app.engines.identity.levenshtein import (
    bounded_levenshtein,
    normalize_identity_text,
)


def test_normalization_is_unicode_case_and_separator_stable() -> None:
    assert normalize_identity_text("  ACME—BANK  Ltd. ") == "acme bank ltd"
    assert normalize_identity_text("ＡＢＣ") == "abc"


@pytest.mark.parametrize(
    "left,right,maximum,expected",
    [
        ("kitten", "sitting", 3, 3),
        ("transaction", "transactoin", 2, 2),
        ("ABC-123", "abc 123", 0, 0),
        ("short", "very long value", 3, None),
        ("abcdef", "uvwxyz", 2, None),
    ],
)
def test_bounded_levenshtein(
    left: str, right: str, maximum: int, expected: int | None
) -> None:
    assert bounded_levenshtein(left, right, maximum) == expected


def test_negative_distance_bound_is_rejected() -> None:
    with pytest.raises(ValueError):
        bounded_levenshtein("a", "b", -1)
