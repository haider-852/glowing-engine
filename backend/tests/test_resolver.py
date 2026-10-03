import pytest

from app.resolver import ResolutionStatus as S


@pytest.mark.parametrize(
    "query, case_id",
    [
        ("Shah Bano", "shah-bano-1985"),
        ("Mohd. Ahmed Khan v. Shah Bano Begum", "shah-bano-1985"),
        ("ADM Jabalpur", "adm-jabalpur-1976"),
        ("Kesavananda", "kesavananda-bharati-1973"),
        ("Keshavanand Bharti", "kesavananda-bharati-1973"),
        ("golak nath", "golak-nath-1967"),
        ("Puttaswamy privacy", "puttaswamy-privacy-2017"),
        ("Puttaswamy Aadhaar", "puttaswamy-aadhaar-2018"),
        ("Maneka Gandhi 1978", "maneka-gandhi-1978"),
        ("Koushal 2014", "suresh-kumar-koushal-2013"),  # report year, not decision year
        ("(1973) 4 SCC 225", "kesavananda-bharati-1973"),
        ("[1967] 2 S.C.R. 762", "golak-nath-1967"),
        ("Kesavananda Bharati (1973) 4 SCC 225", "kesavananda-bharati-1973"),
    ],
)
def test_resolves(resolver, query, case_id):
    r = resolver.resolve(query)
    assert r.status is S.RESOLVED, (r.status, r.message)
    assert r.case.id == case_id


def test_ambiguous_name_asks(resolver):
    r = resolver.resolve("Puttaswamy")
    assert r.status is S.AMBIGUOUS
    assert {c.case.id for c in r.candidates} == {"puttaswamy-privacy-2017", "puttaswamy-aadhaar-2018"}


@pytest.mark.parametrize(
    "query, status",
    [
        ("Sharma v. State of Kerala", S.SUGGESTIONS),  # fake; shares only "Kerala"
        ("Imran Khan v. State of Punjab", S.NOT_FOUND),
        ("Union of India", S.NOT_FOUND),  # nothing distinctive
        ("Maneka Gandhi 1985", S.SUGGESTIONS),  # wrong year
        ("Maneka Gandhi (1973) 4 SCC 225", S.SUGGESTIONS),  # name and citation disagree
        ("(1973) 4 SCC 225 AIR 1978 SC 597", S.AMBIGUOUS),  # citations of two cases
        ("(1973) 4 SCC 999", S.NOT_FOUND),  # plausible but unknown
        ("AIR 1948 SC 12", S.INVALID_CITATION),  # before the Supreme Court existed
        ("(2099) 1 SCC 1", S.INVALID_CITATION),
    ],
)
def test_never_picks_a_case_for_bad_queries(resolver, query, status):
    r = resolver.resolve(query)
    assert r.status is status, (r.status, r.message)
    assert r.case is None


def test_wrong_year_explains(resolver):
    r = resolver.resolve("Maneka Gandhi 1985")
    assert r.candidates[0].case.id == "maneka-gandhi-1978"
    assert "1978" in r.candidates[0].notes[0]


def test_unknown_citation_does_not_claim_case_is_fake(resolver):
    r = resolver.resolve("(1973) 4 SCC 999")
    assert "does not mean the case does not exist" in r.message
