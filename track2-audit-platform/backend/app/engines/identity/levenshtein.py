"""Hand-written Levenshtein edit-distance and normalised similarity.

Uses the classic Wagner-Fischer DP algorithm with a single-row optimisation
that keeps memory at O(min(|a|, |b|)) rather than O(|a|·|b|).

Complexity: O(|a| · |b|) time, O(min(|a|, |b|)) space.
No external libraries are used — pure Python only.
"""

from __future__ import annotations


def levenshtein_distance(a: str, b: str) -> int:
    """Return the minimum edit distance (insert/delete/substitute) between *a* and *b*.

    Swaps so that *a* is always the shorter string to minimise memory.

    Examples:
        levenshtein_distance("kitten", "sitting")  → 3
        levenshtein_distance("",       "abc")       → 3
        levenshtein_distance("abc",    "abc")       → 0
    """
    if a == b:
        return 0
    # Ensure a is the shorter string (memory optimisation)
    if len(a) > len(b):
        a, b = b, a

    len_a = len(a)
    len_b = len(b)

    # prev[j] = distance(a[0:i], b[0:j]) from the previous row
    prev = list(range(len_b + 1))
    curr = [0] * (len_b + 1)

    for i in range(1, len_a + 1):
        curr[0] = i
        for j in range(1, len_b + 1):
            if a[i - 1] == b[j - 1]:
                curr[j] = prev[j - 1]
            else:
                curr[j] = 1 + min(
                    prev[j],      # deletion
                    curr[j - 1],  # insertion
                    prev[j - 1],  # substitution
                )
        prev, curr = curr, prev

    return prev[len_b]


def levenshtein_similarity(a: str, b: str) -> float:
    """Return a normalised similarity ratio in [0.0, 1.0].

    0.0 = completely different; 1.0 = identical.
    Normalises by the length of the longer string so that short strings
    aren't unfairly penalised.

    Examples:
        levenshtein_similarity("abc", "abc")  → 1.0
        levenshtein_similarity("abc", "xyz")  → 0.0
        levenshtein_similarity("",    "")     → 1.0
    """
    if a == b:
        return 1.0
    max_len = max(len(a), len(b))
    if max_len == 0:
        return 1.0
    dist = levenshtein_distance(a, b)
    return 1.0 - dist / max_len
