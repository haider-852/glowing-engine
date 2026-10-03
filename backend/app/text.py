"""Text normalisation and fuzzy matching for case names.

Trigram similarity follows Postgres pg_trgm (lowercase, words padded with two
leading spaces and one trailing space), so results here line up with the
`similarity()` the database will use once the alias table lives in Postgres.
"""

from __future__ import annotations

import re
import unicodedata

# Words that appear in so many Indian case titles that matching on them says
# nothing about which case was meant ("State of Kerala", "Union of India").
STOPWORDS = frozenset(
    """
    v vs versus the of and or a an to for in re by its through
    ors anr others another etc
    state union india govt government
    ltd pvt co company corporation
    case judgment judgement matter
    justice retd dr mr mrs ms smt shri sri
    """.split()
)

# Minimum similarity for two words to count as the same word.
# Catches misspellings like "Kesavanada" / "Keshavananda".
TOKEN_MATCH = 0.45

# Score given to two words that differ only in vowels, "h" or doubled letters,
# the usual variation in transliterated names (Menaka / Maneka, Vishaka /
# Vishakha, Bharati / Bharathi). Enough to count as a match, but lower than a
# close spelling, since unrelated names can share a skeleton.
SKELETON_MATCH = 0.6

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = text.lower().replace("&", " and ")
    return _NON_ALNUM.sub(" ", text).strip()


def tokens(text: str) -> list[str]:
    return normalize(text).split()


def distinctive_tokens(text: str) -> list[str]:
    """Tokens that help identify a case: no stopwords, numbers or initials.

    Anything shorter than three letters is treated as initials, whether written
    "I.C." or "IC".
    """
    return [t for t in tokens(text) if t not in STOPWORDS and not t.isdigit() and len(t) > 2]


def _word_trigrams(word: str) -> set[str]:
    padded = f"  {word} "
    return {padded[i : i + 3] for i in range(len(padded) - 2)}


def trigrams(text: str) -> set[str]:
    out: set[str] = set()
    for word in tokens(text):
        out |= _word_trigrams(word)
    return out


def skeleton(word: str) -> str:
    """Consonant outline of a word: "keshavananda" and "kesavananda" -> "ksvnd"."""
    out = []
    for ch in word.replace("w", "v"):
        if ch in "aeiouyh" or (out and out[-1] == ch):
            continue
        out.append(ch)
    return "".join(out)


def word_similarity(a: str, b: str) -> float:
    sim = trigram_similarity(a, b)
    if sim < SKELETON_MATCH and len(sk := skeleton(a)) >= 3 and sk == skeleton(b):
        return SKELETON_MATCH
    return sim


def trigram_similarity(a: str, b: str) -> float:
    ta, tb = trigrams(a), trigrams(b)
    if not ta or not tb:
        return 0.0
    shared = len(ta & tb)
    return shared / (len(ta) + len(tb) - shared)


def _with_joined_pairs(toks: list[str]) -> list[str]:
    # "golak nath" should match "golaknath".
    return toks + [a + b for a, b in zip(toks, toks[1:], strict=False)]


def best_token_scores(source: list[str], target: list[str]) -> list[float]:
    """For each source token, its best similarity to any target token."""
    pool = _with_joined_pairs(target)
    if not pool:
        return [0.0 for _ in source]
    return [max(word_similarity(s, t) for t in pool) for s in source]


def coverage(source: list[str], target: list[str], threshold: float = TOKEN_MATCH) -> float:
    """Share of source tokens that have a match in target."""
    if not source:
        return 0.0
    scores = best_token_scores(source, target)
    return sum(1 for s in scores if s >= threshold) / len(source)


def titles_match(a: str, b: str, threshold: float = 0.8) -> bool:
    """Whether two titles plausibly name the same case.

    Sources word titles differently ("... and Ors.", "His Holiness ..."), so
    the shorter title's distinctive words must appear in the longer one.
    """
    ta, tb = distinctive_tokens(a), distinctive_tokens(b)
    if not ta or not tb:
        return False
    shorter, longer = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return coverage(shorter, longer) >= threshold
