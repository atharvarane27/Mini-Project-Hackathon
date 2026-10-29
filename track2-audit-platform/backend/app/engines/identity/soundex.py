"""Hand-written Soundex algorithm for phonetic blocking of account/payee names.

Implements the standard American Soundex (Russell & Odell, 1918) encoding:
  1. Retain first letter.
  2. Map remaining letters to digits per the Soundex table;
     ignore H and W; drop A, E, I, O, U (vowels) after encoding.
  3. Collapse adjacent duplicate codes (including across H/W).
  4. Pad or truncate to exactly 4 characters (letter + 3 digits).

Complexity: O(n) where n = len(name).
No external libraries are used — pure Python only.
"""

from __future__ import annotations

# Soundex digit table — 0 means "ignore / vowel"
_SOUNDEX_TABLE: dict[str, str] = {
    "B": "1",
    "F": "1",
    "P": "1",
    "V": "1",
    "C": "2",
    "G": "2",
    "J": "2",
    "K": "2",
    "Q": "2",
    "S": "2",
    "X": "2",
    "Z": "2",
    "D": "3",
    "T": "3",
    "L": "4",
    "M": "5",
    "N": "5",
    "R": "6",
    # Vowels (A E I O U) and H, W → "0" (ignored)
    "A": "0",
    "E": "0",
    "I": "0",
    "O": "0",
    "U": "0",
    "H": "0",
    "W": "0",
    "Y": "0",
}


def soundex(name: str) -> str:
    """Return the 4-character Soundex code for *name*.

    Non-ASCII characters are stripped. Empty or all-non-alpha input
    returns '0000'.

    Examples:
        soundex("Robert")  → "R163"
        soundex("Rupert")  → "R163"
        soundex("Smith")   → "S530"
        soundex("")        → "0000"
    """
    # Normalise: uppercase ASCII letters only
    cleaned = "".join(ch for ch in name.upper() if ch.isalpha() and ch.isascii())
    if not cleaned:
        return "0000"

    first_letter = cleaned[0]
    first_code = _SOUNDEX_TABLE.get(first_letter, "0")

    code_digits: list[str] = []
    prev_code = first_code  # used for adjacent-duplicate collapse

    for ch in cleaned[1:]:
        digit = _SOUNDEX_TABLE.get(ch, "0")
        if digit == "0":
            # H and W do not break adjacency; vowels do break it
            if ch not in ("H", "W"):
                prev_code = digit  # vowel resets adjacency
            # else H/W: leave prev_code unchanged (transparent)
            continue
        if digit != prev_code:
            code_digits.append(digit)
            if len(code_digits) == 3:
                break
        prev_code = digit

    padded = "".join(code_digits).ljust(3, "0")
    return first_letter + padded


def soundex_similarity(name_a: str, name_b: str) -> bool:
    """Return True if both names share the same Soundex code."""
    return soundex(name_a) == soundex(name_b)
