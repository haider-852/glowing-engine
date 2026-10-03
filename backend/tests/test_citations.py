from datetime import date

import pytest

from app.citations import find_citations, parse_citation, plausibility_issues


@pytest.mark.parametrize(
    "text, canonical, reporter_key",
    [
        ("(1973) 4 SCC 225", "(1973) 4 SCC 225", "SCC"),
        ("(1973) 4 S.C.C. 225", "(1973) 4 SCC 225", "SCC"),
        ("1992 Supp (3) SCC 217", "1992 Supp (3) SCC 217", "SCC"),
        ("1992 Supp. (3) S.C.C. 217", "1992 Supp (3) SCC 217", "SCC"),
        ("(2010) 2 SCC (Cri) 123", "(2010) 2 SCC (Cri) 123", "SCC (Cri)"),
        ("(2010) 2 SCC (L&S) 45", "(2010) 2 SCC (L&S) 45", "SCC (L&S)"),
        ("AIR 1978 SC 597", "AIR 1978 SC 597", "AIR SC"),
        ("A.I.R. 1978 S.C. 597", "AIR 1978 SC 597", "AIR SC"),
        ("AIR 1990 Bom 12", "AIR 1990 Bom 12", "AIR Bom"),
        ("[1967] 2 SCR 762", "[1967] 2 SCR 762", "SCR"),
        ("(1967) 2 S.C.R. 762", "[1967] 2 SCR 762", "SCR"),
        ("[1973] Supp. S.C.R. 1", "[1973] Supp SCR 1", "SCR"),
        ("[2023] 1 S.C.R. 1", "[2023] 1 SCR 1", "SCR"),
        ("(2017) 10 SCALE 1", "(2017) 10 SCALE 1", "SCALE"),
        ("JT 2017 (10) SC 1", "JT 2017 (10) SC 1", "JT"),
        ("2023 INSC 1", "2023 INSC 1", "INSC"),
        ("2024 insc 512", "2024 INSC 512", "INSC"),
    ],
)
def test_parse_and_canonicalise(text, canonical, reporter_key):
    cit = parse_citation(text)
    assert cit is not None, text
    assert cit.canonical == canonical
    assert cit.reporter_key == reporter_key
    # The canonical form must parse back to the same citation.
    assert parse_citation(cit.canonical) == cit


@pytest.mark.parametrize("text", ["Shah Bano", "SCC 225", "(1973) SCC", "1973 4 225", "AIR SC 597", ""])
def test_rejects_non_citations(text):
    assert parse_citation(text) is None


def test_parse_requires_whole_string():
    assert parse_citation("Kesavananda (1973) 4 SCC 225") is None


def test_finds_several_citations_in_text():
    found = find_citations("Kesavananda Bharati, (1973) 4 SCC 225 : AIR 1973 SC 1461, overruling [1967] 2 SCR 762")
    assert [c.canonical for c in found] == ["(1973) 4 SCC 225", "AIR 1973 SC 1461", "[1967] 2 SCR 762"]


TODAY = date(2026, 10, 3)


@pytest.mark.parametrize(
    "text, issue",
    [
        ("(2099) 1 SCC 1", "future"),
        ("AIR 1948 SC 12", "before 1950"),
        ("(1965) 1 SCC 1", "before 1969"),
        ("[1949] 1 SCR 1", "before 1950"),
        ("(1980) 3 SCC 0", "page"),
    ],
)
def test_implausible_citations(text, issue):
    issues = plausibility_issues(parse_citation(text), today=TODAY)
    assert any(issue in i for i in issues), issues


@pytest.mark.parametrize("text", ["(1973) 4 SCC 225", "AIR 1950 SC 27", "AIR 1945 Bom 1", "2026 INSC 1"])
def test_plausible_citations(text):
    assert plausibility_issues(parse_citation(text), today=TODAY) == []
