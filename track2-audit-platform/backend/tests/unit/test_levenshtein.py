"""Unit tests for the hand-written Levenshtein edit-distance algorithm.

Tests cover:
- Exact distance calculation for known pairs
- Symmetry: distance(a, b) == distance(b, a)
- Edge cases: empty strings, identical strings, single-char
- Normalised similarity ratio
- Triangle inequality does not need to hold but distance metric properties do
"""

import pytest

from app.engines.identity.levenshtein import levenshtein_distance, levenshtein_similarity


class TestLevenshteinDistance:
    def test_identical_strings(self) -> None:
        assert levenshtein_distance("abc", "abc") == 0

    def test_empty_to_word(self) -> None:
        assert levenshtein_distance("", "abc") == 3

    def test_word_to_empty(self) -> None:
        assert levenshtein_distance("abc", "") == 3

    def test_both_empty(self) -> None:
        assert levenshtein_distance("", "") == 0

    def test_single_substitution(self) -> None:
        assert levenshtein_distance("cat", "bat") == 1

    def test_single_insertion(self) -> None:
        assert levenshtein_distance("cat", "cats") == 1

    def test_single_deletion(self) -> None:
        assert levenshtein_distance("cats", "cat") == 1

    def test_kitten_sitting(self) -> None:
        # Classic example: kitten → sitting requires 3 edits
        assert levenshtein_distance("kitten", "sitting") == 3

    def test_sunday_saturday(self) -> None:
        assert levenshtein_distance("Sunday", "Saturday") == 3

    def test_symmetry(self) -> None:
        pairs = [("abc", "xyz"), ("kitten", "sitting"), ("", "abc"), ("a", "b")]
        for a, b in pairs:
            assert levenshtein_distance(a, b) == levenshtein_distance(b, a), (
                f"Symmetry failed for ({a!r}, {b!r})"
            )

    def test_longer_string_swapped(self) -> None:
        # "longer_string" has 13 chars, "x" has 1 char with no character in common
        # Edit distance = 13 (replace L→x, delete remaining 12) = 13 total edits
        assert levenshtein_distance("longer_string", "x") == 13

    def test_unicode_characters(self) -> None:
        # Should not crash; treats each Unicode code point as one character
        dist = levenshtein_distance("café", "cafe")
        assert isinstance(dist, int)
        assert dist >= 0

    def test_completely_different(self) -> None:
        assert levenshtein_distance("abc", "xyz") == 3

    def test_one_char_diff(self) -> None:
        assert levenshtein_distance("abcd", "abce") == 1


class TestLevenshteinSimilarity:
    def test_identical_is_one(self) -> None:
        assert levenshtein_similarity("abc", "abc") == pytest.approx(1.0)

    def test_both_empty_is_one(self) -> None:
        assert levenshtein_similarity("", "") == pytest.approx(1.0)

    def test_completely_different_low_similarity(self) -> None:
        ratio = levenshtein_similarity("abc", "xyz")
        assert ratio == pytest.approx(0.0)

    def test_ratio_in_range(self) -> None:
        ratio = levenshtein_similarity("kitten", "sitting")
        assert 0.0 <= ratio <= 1.0

    def test_one_edit_close_to_one(self) -> None:
        ratio = levenshtein_similarity("cat", "bat")
        assert ratio == pytest.approx(2 / 3)

    def test_john_doe_variant(self) -> None:
        # "JOHN DOE" vs "Jon Doe" — should be fairly similar
        ratio = levenshtein_similarity("john doe", "jon doe")
        assert ratio >= 0.75, f"Expected >= 0.75, got {ratio}"

    def test_symmetry(self) -> None:
        a, b = "hello", "world"
        assert levenshtein_similarity(a, b) == pytest.approx(levenshtein_similarity(b, a))
