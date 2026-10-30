"""Unit tests for bounded Levenshtein distance and text normalization."""

from app.engines.identity.levenshtein import levenshtein_distance, levenshtein_similarity, normalize_text


class TestLevenshteinDistance:
    def test_identical_strings(self) -> None:
        assert levenshtein_distance("abc", "abc") == 0

    def test_empty_to_word(self) -> None:
        assert levenshtein_distance("", "abc") == 3

    def test_word_to_empty(self) -> None:
        assert levenshtein_distance("abc", "") == 3

    def test_single_substitution(self) -> None:
        assert levenshtein_distance("cat", "bat") == 1

    def test_single_insertion(self) -> None:
        assert levenshtein_distance("cat", "cats") == 1

    def test_kitten_sitting(self) -> None:
        assert levenshtein_distance("kitten", "sitting") == 3

    def test_symmetry(self) -> None:
        pairs = [("abc", "xyz"), ("kitten", "sitting"), ("", "abc"), ("a", "b")]
        for a, b in pairs:
            assert levenshtein_distance(a, b) == levenshtein_distance(b, a)

    def test_normalization_reduces_case_and_whitespace_noise(self) -> None:
        assert levenshtein_distance("  JOHN DOE  ", "john   doe") == 0
        assert normalize_text("  JOHN   DOE ") == "john doe"


class TestLevenshteinSimilarity:
    def test_identical_is_one(self) -> None:
        assert levenshtein_similarity("abc", "abc") == 1.0

    def test_different_strings_low_similarity(self) -> None:
        assert levenshtein_similarity("abc", "xyz") == 0.0

    def test_typo_is_high_similarity(self) -> None:
        ratio = levenshtein_similarity("john doe", "jon doe")
        assert ratio >= 0.75

    def test_ratio_is_in_range(self) -> None:
        ratio = levenshtein_similarity("hello", "world")
        assert 0.0 <= ratio <= 1.0
