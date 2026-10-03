"""Decide whether a case is verified, from the records the sources returned.

A case is VERIFIED only when all of these hold:

* at least two records come from independent origins (two sources that
  republish the same upstream text count once);
* at least one record is from an official source (the Supreme Court website
  or Digital SCR);
* every record's title matches the others and the case the user asked for;
* the decision date was reported by two or more records, and they agree;
* the bench, and every citation reported in the same reporter, agree.

If identity cannot be established (no records, one origin, no official source,
or titles that disagree) the result is COULD_NOT_VERIFY. If identity holds but
a detail differs, the result is PARTLY_VERIFIED, listing the fields that differ.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

from .cases import CaseEntry
from .citations import parse_citation
from .text import titles_match, tokens

_JUDGE_HONORIFICS = {"justice", "j", "cji", "hon", "ble", "honble", "mr", "mrs", "ms", "dr", "chief"}


class VerificationStatus(StrEnum):
    VERIFIED = "verified"
    PARTLY_VERIFIED = "partly_verified"
    COULD_NOT_VERIFY = "could_not_verify"


@dataclass(frozen=True)
class SourceRecord:
    """What one source says about a case."""

    source: str  # e.g. "sc_website", "digital_scr", "indian_kanoon"
    # Where the source got the case from. Records with the same origin are not
    # independent: a site that republishes the SC website's text is a copy of
    # the SC website, not a second witness.
    origin: str
    official: bool
    title: str
    retrieved_at: datetime
    decision_date: date | None = None
    judges: tuple[str, ...] = ()
    citations: tuple[str, ...] = ()
    url: str | None = None


@dataclass
class FieldDiff:
    field: str
    values: dict[str, str]  # source -> value


@dataclass
class VerificationResult:
    status: VerificationStatus
    reasons: list[str] = field(default_factory=list)
    differences: list[FieldDiff] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)


def _judge_key(name: str) -> frozenset[str]:
    # Drop initials and honorifics: "Y.V. Chandrachud, J." -> {"chandrachud"}.
    return frozenset(t for t in tokens(name) if len(t) > 1 and t not in _JUDGE_HONORIFICS)


def same_bench(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    if len(a) != len(b):
        return False
    remaining = [_judge_key(j) for j in b]
    for judge in a:
        key = _judge_key(judge)
        hit = next((i for i, other in enumerate(remaining) if key and other and (key <= other or other <= key)), None)
        if hit is None:
            return False
        remaining.pop(hit)
    return True


def verify(records: list[SourceRecord], expected: CaseEntry | None = None) -> VerificationResult:
    sources = [r.source for r in records]

    def fail(reason: str) -> VerificationResult:
        return VerificationResult(VerificationStatus.COULD_NOT_VERIFY, [reason], sources=sources)

    if not records:
        return fail("No source returned this case.")
    if len({r.origin for r in records}) < 2:
        return fail("Only one independent source has this case; at least two are needed.")
    if not any(r.official for r in records):
        return fail("No official source (Supreme Court website or Digital SCR) has this case.")

    first = records[0]
    for r in records[1:]:
        if not titles_match(first.title, r.title):
            return fail(
                f"The sources describe different cases: {first.title!r} ({first.source}) vs {r.title!r} ({r.source})."
            )
    if expected and not any(titles_match(n, first.title) for n in expected.names):
        return fail(f"The sources returned {first.title!r}, not {expected.title!r}.")

    checked = ["title"]
    differences: list[FieldDiff] = []
    reasons: list[str] = []

    dated = [r for r in records if r.decision_date]
    if len(dated) >= 2:
        checked.append("decision_date")
        if len({r.decision_date for r in dated}) > 1:
            differences.append(FieldDiff("decision_date", {r.source: r.decision_date.isoformat() for r in dated}))
    else:
        reasons.append("The decision date was not confirmed by two sources.")
    if expected and dated and all(r.decision_date.year != expected.year for r in dated):
        differences.append(
            FieldDiff("year", {"our_table": str(expected.year)} | {r.source: str(r.decision_date.year) for r in dated})
        )

    benches = [r for r in records if r.judges]
    if len(benches) >= 2:
        checked.append("bench")
        if not all(same_bench(benches[0].judges, r.judges) for r in benches[1:]):
            differences.append(FieldDiff("bench", {r.source: ", ".join(r.judges) for r in benches}))
    if expected and expected.bench_strength and benches:
        if any(len(r.judges) != expected.bench_strength for r in benches):
            differences.append(
                FieldDiff(
                    "bench_strength",
                    {"our_table": str(expected.bench_strength)} | {r.source: str(len(r.judges)) for r in benches},
                )
            )

    by_key: dict[str, dict[str, str]] = {}
    for r in records:
        for text in r.citations:
            cit = parse_citation(text)
            if cit is None:
                reasons.append(f"{r.source} gave a citation we could not read: {text!r}.")
                continue
            by_key.setdefault(cit.reporter_key, {})[r.source] = cit.canonical
    if expected:
        for cit in expected.citations:
            by_key.setdefault(cit.reporter_key, {})["our_table"] = cit.canonical
    for key, values in sorted(by_key.items()):
        if len(values) >= 2:
            checked.append(f"citation:{key}")
            if len(set(values.values())) > 1:
                differences.append(FieldDiff(f"citation:{key}", values))

    if differences or reasons:
        reasons = [f"Sources differ on {d.field}." for d in differences] + reasons
        return VerificationResult(VerificationStatus.PARTLY_VERIFIED, reasons, differences, checked, sources)
    return VerificationResult(VerificationStatus.VERIFIED, [], [], checked, sources)
