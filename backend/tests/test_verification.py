"""Verification rules, tested on made-up records.

The records here are synthetic. They test the rules, not any real case.
"""

from dataclasses import replace
from datetime import date, datetime

from app.cases import CaseEntry
from app.citations import parse_citation
from app.verification import SourceRecord, same_bench, verify
from app.verification import VerificationStatus as V

NOW = datetime(2026, 10, 3, 12, 0)
BENCH = ("A.B. Rao", "C. Mehta", "D.E. Iyer")

OFFICIAL = SourceRecord(
    source="sc_website",
    origin="sc_website",
    official=True,
    title="Asha Devi v. State of Example",
    retrieved_at=NOW,
    decision_date=date(1990, 5, 1),
    judges=BENCH,
    citations=("[1990] 2 SCR 100",),
)
REPORT = replace(
    OFFICIAL,
    source="digital_scr",
    origin="digital_scr",
    title="Smt. Asha Devi and Ors. v. State of Example and Anr.",
    judges=("Rao, A.B., J.", "Mehta, C., J.", "Iyer, D.E., J."),
)
AGGREGATOR = replace(
    OFFICIAL,
    source="indian_kanoon",
    origin="indian_kanoon",
    official=False,
    citations=("[1990] 2 SCR 100", "(1990) 3 SCC 50", "AIR 1990 SC 900"),
)
EXPECTED = CaseEntry(
    id="asha-devi-1990",
    title="Asha Devi v. State of Example",
    year=1990,
    bench_strength=3,
    citations=(parse_citation("(1990) 3 SCC 50"), parse_citation("AIR 1990 SC 900")),
)


def test_verified_with_official_and_independent_source():
    result = verify([OFFICIAL, AGGREGATOR], expected=EXPECTED)
    assert result.status is V.VERIFIED, result.reasons
    assert {"title", "decision_date", "bench", "citation:SCR", "citation:SCC", "citation:AIR SC"} <= set(result.checked)


def test_two_official_sources_verify():
    assert verify([OFFICIAL, REPORT]).status is V.VERIFIED


def test_no_records():
    assert verify([], expected=EXPECTED).status is V.COULD_NOT_VERIFY


def test_one_source_is_not_enough():
    assert verify([OFFICIAL], expected=EXPECTED).status is V.COULD_NOT_VERIFY


def test_copies_of_one_origin_count_once():
    mirror = replace(AGGREGATOR, origin="sc_website")
    result = verify([OFFICIAL, mirror], expected=EXPECTED)
    assert result.status is V.COULD_NOT_VERIFY
    assert "independent" in result.reasons[0]


def test_needs_an_official_source():
    other = replace(AGGREGATOR, source="other_site", origin="other_site")
    result = verify([AGGREGATOR, other], expected=EXPECTED)
    assert result.status is V.COULD_NOT_VERIFY
    assert "official" in result.reasons[0]


def test_different_titles_mean_different_cases():
    wrong = replace(AGGREGATOR, title="Ramesh Kumar v. Union of India")
    assert verify([OFFICIAL, wrong]).status is V.COULD_NOT_VERIFY


def test_records_must_be_the_case_that_was_asked_for():
    other = CaseEntry(id="x", title="Ramesh Kumar v. Union of India", year=1990)
    assert verify([OFFICIAL, AGGREGATOR], expected=other).status is V.COULD_NOT_VERIFY


def test_date_mismatch_is_partly_verified():
    late = replace(AGGREGATOR, decision_date=date(1990, 5, 2))
    result = verify([OFFICIAL, late], expected=EXPECTED)
    assert result.status is V.PARTLY_VERIFIED
    assert [d.field for d in result.differences] == ["decision_date"]


def test_citation_mismatch_is_partly_verified():
    wrong = replace(AGGREGATOR, citations=("[1990] 2 SCR 101",))
    result = verify([OFFICIAL, wrong])
    assert result.status is V.PARTLY_VERIFIED
    assert result.differences[0].values == {"sc_website": "[1990] 2 SCR 100", "indian_kanoon": "[1990] 2 SCR 101"}


def test_citation_must_match_our_table():
    wrong = replace(AGGREGATOR, citations=("(1990) 3 SCC 51",))
    result = verify([OFFICIAL, wrong], expected=EXPECTED)
    assert result.status is V.PARTLY_VERIFIED
    assert result.differences[0].field == "citation:SCC"


def test_bench_mismatch_is_partly_verified():
    wrong = replace(AGGREGATOR, judges=("A.B. Rao", "C. Mehta", "F. Khan"))
    assert verify([OFFICIAL, wrong]).status is V.PARTLY_VERIFIED


def test_bench_strength_must_match_our_table():
    wrong = replace(EXPECTED, bench_strength=5)
    result = verify([OFFICIAL, AGGREGATOR], expected=wrong)
    assert result.status is V.PARTLY_VERIFIED
    assert result.differences[0].field == "bench_strength"


def test_unconfirmed_date_is_partly_verified():
    undated = replace(AGGREGATOR, decision_date=None)
    result = verify([OFFICIAL, undated])
    assert result.status is V.PARTLY_VERIFIED
    assert "decision date" in result.reasons[0]


def test_same_bench_ignores_order_initials_and_honorifics():
    assert same_bench(BENCH, ("Iyer, J.", "Hon'ble Mr. Justice C. Mehta", "Rao A.B."))
    assert not same_bench(BENCH, BENCH[:2])
