"""Unit tests for the hand-written Soundex phonetic encoder.

Tests cover:
- Standard Soundex encoding examples
- Edge cases: empty string, single character, all-vowels, H/W adjacency
- Phonetic similarity between name variants
"""


from app.engines.identity.soundex import soundex, soundex_similarity


class TestSoundexEncoding:
    def test_robert_rupert_same_code(self) -> None:
        assert soundex("Robert") == soundex("Rupert") == "R163"

    def test_smith(self) -> None:
        assert soundex("Smith") == "S530"

    def test_smythe(self) -> None:
        # S, M=5, th→T=3, e=vowel → S530
        assert soundex("Smythe") == "S530"

    def test_washington(self) -> None:
        assert soundex("Washington") == "W252"

    def test_lee(self) -> None:
        # L, e=0, e=0 → L000
        assert soundex("Lee") == "L000"

    def test_gutierrez(self) -> None:
        assert soundex("Gutierrez") == "G362"

    def test_jackson(self) -> None:
        assert soundex("Jackson") == "J250"

    def test_empty_string_returns_zero_code(self) -> None:
        assert soundex("") == "0000"

    def test_single_letter(self) -> None:
        result = soundex("A")
        assert result == "A000"

    def test_all_vowels(self) -> None:
        result = soundex("AEIOU")
        assert result == "A000"

    def test_pads_to_four_chars(self) -> None:
        result = soundex("B")
        assert len(result) == 4
        assert result == "B000"

    def test_truncates_to_four_chars(self) -> None:
        result = soundex("Bermingham")
        assert len(result) == 4

    def test_case_insensitive(self) -> None:
        assert soundex("Smith") == soundex("smith") == soundex("SMITH")

    def test_hw_transparent_adjacency(self) -> None:
        # Ashcraft: A, S=2, H is transparent, C=2 → don't add second 2
        # Then R=6, A=vowel, F=1, T=3 → A261
        result = soundex("Ashcraft")
        assert result == "A261"

    def test_non_ascii_stripped(self) -> None:
        # Non-ASCII letters are stripped — should not crash
        result = soundex("Müller")
        assert len(result) == 4


class TestSoundexSimilarity:
    def test_same_name_is_similar(self) -> None:
        assert soundex_similarity("Robert", "Robert") is True

    def test_phonetic_variants_are_similar(self) -> None:
        assert soundex_similarity("Robert", "Rupert") is True

    def test_different_names_not_similar(self) -> None:
        assert soundex_similarity("Smith", "Jones") is False

    def test_empty_strings_both_zero(self) -> None:
        assert soundex_similarity("", "") is True

    def test_one_empty_not_similar(self) -> None:
        assert soundex_similarity("Smith", "") is False
