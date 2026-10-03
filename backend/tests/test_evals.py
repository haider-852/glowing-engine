from datetime import date, datetime

from app.cases import CaseEntry
from app.pipeline import lookup
from app.verification import SourceRecord, VerificationStatus
from evals.run import run_eval


def test_release_gates_pass():
    report = run_eval()
    assert report.passed, report.failures


class AgreeableStore:
    """A retriever that returns two matching official records for any case it
    is asked about, including ones that should never have reached it. Used to
    check that trap queries fail at resolution, before verification."""

    def records_for(self, case: CaseEntry) -> list[SourceRecord]:
        base = dict(
            title=case.title,
            retrieved_at=datetime(2026, 10, 3),
            decision_date=date(case.year, 1, 1),
            citations=tuple(c.canonical for c in case.citations),
        )
        return [
            SourceRecord(source="sc_website", origin="sc_website", official=True, **base),
            SourceRecord(source="digital_scr", origin="digital_scr", official=True, **base),
        ]


def test_traps_never_verified_even_if_the_retriever_agrees_with_everything():
    report = run_eval(store=AgreeableStore())
    assert report.metrics["fake_cases_verified"] == 0
    assert report.passed, report.failures


def test_real_case_verifies_when_sources_agree(resolver):
    result = lookup("Shah Bano", resolver, AgreeableStore())
    assert result.verification.status is VerificationStatus.VERIFIED


def test_nothing_verifies_without_a_retriever(resolver):
    from app.pipeline import NullSourceStore

    result = lookup("Shah Bano", resolver, NullSourceStore())
    assert result.resolution.case.id == "shah-bano-1985"
    assert result.verification.status is VerificationStatus.COULD_NOT_VERIFY
