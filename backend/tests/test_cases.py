import pytest

from app.cases import CaseTableError, load_cases


def test_seed_loads(cases):
    assert len(cases) >= 10
    assert all(c.citations for c in cases)


def test_seed_is_marked_unchecked(cases):
    # The seed was typed from memory. Flipping this flag means a person checked
    # the entry against an official source; do it per entry, not in bulk.
    assert not any(c.checked_against_source for c in cases)


def test_years_include_report_year(cases):
    koushal = next(c for c in cases if c.id == "suresh-kumar-koushal-2013")
    assert koushal.years == {2013, 2014}


def _write(tmp_path, body):
    p = tmp_path / "cases.yaml"
    p.write_text(body)
    return p


def test_rejects_unparseable_citation(tmp_path):
    p = _write(tmp_path, "cases:\n  - {id: a, title: A v. B, year: 1980, citations: ['not a citation']}\n")
    with pytest.raises(CaseTableError, match="cannot parse"):
        load_cases(p)


def test_rejects_implausible_citation(tmp_path):
    p = _write(tmp_path, "cases:\n  - {id: a, title: A v. B, year: 1948, citations: ['AIR 1948 SC 1']}\n")
    with pytest.raises(CaseTableError, match="before 1950"):
        load_cases(p)


def test_rejects_citation_shared_by_two_cases(tmp_path):
    p = _write(
        tmp_path,
        "cases:\n"
        "  - {id: a, title: A v. B, year: 1980, citations: ['(1980) 1 SCC 1']}\n"
        "  - {id: b, title: C v. D, year: 1980, citations: ['(1980) 1 S.C.C. 1']}\n",
    )
    with pytest.raises(CaseTableError, match="both a and b"):
        load_cases(p)


def test_rejects_two_citations_in_one_reporter(tmp_path):
    p = _write(
        tmp_path, "cases:\n  - {id: a, title: A v. B, year: 1980, citations: ['(1980) 1 SCC 1', '(1980) 2 SCC 5']}\n"
    )
    with pytest.raises(CaseTableError, match="same reporter"):
        load_cases(p)


def test_rejects_duplicate_ids(tmp_path):
    p = _write(tmp_path, "cases:\n  - {id: a, title: A v. B, year: 1980}\n  - {id: a, title: C v. D, year: 1981}\n")
    with pytest.raises(CaseTableError, match="duplicate"):
        load_cases(p)
