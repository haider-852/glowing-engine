import pytest

from app.text import distinctive_tokens, skeleton, titles_match, trigram_similarity, word_similarity


def test_distinctive_tokens_drop_noise():
    assert distinctive_tokens("I.C. Golak Nath and Ors. v. State of Punjab & Anr.") == ["golak", "nath", "punjab"]
    assert distinctive_tokens("IC Golak Nath") == ["golak", "nath"]


def test_trigram_similarity_matches_pg_trgm():
    # Values from Postgres: SELECT similarity('word', 'words') -> 0.5714286
    assert trigram_similarity("word", "words") == pytest.approx(0.5714286, abs=1e-6)
    assert trigram_similarity("abc", "abc") == 1.0
    assert trigram_similarity("abc", "xyz") == 0.0


@pytest.mark.parametrize("a, b", [("menaka", "maneka"), ("vishakha", "vishaka"), ("bharathi", "bharati")])
def test_transliteration_variants_match(a, b):
    assert skeleton(a) == skeleton(b)
    assert word_similarity(a, b) >= 0.45


def test_unrelated_names_do_not_match():
    assert word_similarity("sharma", "shah") < 0.45


def test_titles_match():
    assert titles_match("Smt. Asha Devi and Ors. v. State of Example", "Asha Devi v. State of Example")
    assert not titles_match("Asha Devi v. State of Example", "Ramesh Kumar v. Union of India")
