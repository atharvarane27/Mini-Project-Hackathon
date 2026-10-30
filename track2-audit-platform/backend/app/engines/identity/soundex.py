"""Small deterministic American Soundex implementation."""

from __future__ import annotations

import unicodedata


_CODES = {
    **dict.fromkeys("BFPV", "1"),
    **dict.fromkeys("CGJKQSXZ", "2"),
    **dict.fromkeys("DT", "3"),
    "L": "4",
    **dict.fromkeys("MN", "5"),
    "R": "6",
}


def soundex(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    letters = [character for character in ascii_value.upper() if "A" <= character <= "Z"]
    if not letters:
        return "0000"
    first = letters[0]
    previous = _CODES.get(first, "0")
    digits: list[str] = []
    for character in letters[1:]:
        if character in "HW":
            continue
        code = _CODES.get(character, "0")
        if code != "0" and code != previous:
            digits.append(code)
        previous = code
    return (first + "".join(digits) + "000")[:4]
