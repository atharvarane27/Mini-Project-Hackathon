"""P05 custom Soundex tests."""

from app.engines.identity.soundex import soundex


def test_standard_soundex_examples_and_unicode_normalization() -> None:
    assert soundex("Robert") == soundex("Rupert") == "R163"
    assert soundex("Ashcraft") == "A261"
    assert soundex("Tymczak") == "T522"
    assert soundex("José") == soundex("Jose")
    assert soundex("---") == "0000"
