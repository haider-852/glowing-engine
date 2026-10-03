"""Checks that the database itself refuses unsafe rows.

Runs only when DATABASE_URL points at a database with db/migrations applied.
"""

import os

import pytest

psycopg = pytest.importorskip("psycopg")
DATABASE_URL = os.environ.get("DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE_URL, reason="DATABASE_URL not set")


@pytest.fixture
def cur():
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            yield cur
        conn.rollback()


def _case(cur, slug, **cols):
    cols = {"slug": slug, "title": f"{slug} v. State", **cols}
    names = ", ".join(cols)
    marks = ", ".join(["%s"] * len(cols))
    cur.execute(f"INSERT INTO cases ({names}) VALUES ({marks}) RETURNING id", list(cols.values()))
    return cur.fetchone()[0]


def test_case_cannot_be_verified_without_a_timestamp(cur):
    with pytest.raises(psycopg.errors.CheckViolation):
        _case(cur, "a", verification_status="verified")


def test_bench_size_must_match_judges(cur):
    with pytest.raises(psycopg.errors.CheckViolation):
        _case(cur, "a", bench_strength=3, judges=["Rao", "Mehta"])


def test_citation_belongs_to_one_case(cur):
    a, b = _case(cur, "a"), _case(cur, "b")
    sql = (
        "INSERT INTO citations (case_id, canonical, reporter, reporter_key, year, page)"
        " VALUES (%s, %s, 'SCC', 'SCC', 1980, 1)"
    )
    cur.execute(sql, (a, "(1980) 1 SCC 1"))
    with pytest.raises(psycopg.errors.UniqueViolation):
        cur.execute(sql, (b, "(1980) 1 SCC 1"))


def _edge(cur, **cols):
    a, b = _case(cur, "citing"), _case(cur, "cited")
    cols = {
        "citing_case_id": a,
        "cited_case_id": b,
        "treatment": "overruled",
        "evidence_quote": "...",
        "confidence": 0.9,
        "model": "test",
        "prompt_version": "v0",
        **cols,
    }
    names = ", ".join(cols)
    marks = ", ".join(["%s"] * len(cols))
    cur.execute(f"INSERT INTO citing_edges ({names}) VALUES ({marks})", list(cols.values()))


def test_treatment_cannot_be_confirmed_without_a_reviewer(cur):
    with pytest.raises(psycopg.errors.CheckViolation):
        _edge(cur, review_status="confirmed")


def test_reviewed_treatment_is_accepted(cur):
    _edge(cur, review_status="confirmed", reviewer="annotator-1", reviewed_at="2026-10-03T12:00:00Z")


def test_unknown_treatment_is_rejected(cur):
    with pytest.raises(psycopg.errors.CheckViolation):
        _edge(cur, treatment="sort_of_overruled")
