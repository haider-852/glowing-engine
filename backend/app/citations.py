"""Parse Indian law-report citations.

Supported formats:

    SCC     (1973) 4 SCC 225 · 1992 Supp (3) SCC 217 · (2010) 2 SCC (Cri) 123
    AIR     AIR 1978 SC 597
    SCR     [1967] 2 SCR 762 · [1973] Supp SCR 1 · [2023] 1 S.C.R. 1
    SCALE   (2017) 10 SCALE 1
    JT      JT 2017 (10) SC 1
    INSC    2023 INSC 1  (Supreme Court neutral citation)

Parsing is purely syntactic. A citation that parses is not evidence that a case
exists. `plausibility_issues` rejects citations that cannot be real, and the
verification step decides whether a case is confirmed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

SC_FOUNDED = 1950

# First year a reporter carried Supreme Court judgments, where we are sure of
# it. Anything not listed falls back to SC_FOUNDED.
REPORTER_FIRST_YEAR = {"SCC": 1969}

# AIR court codes that stay upper case; others are title-cased ("Bom", "Del").
_UPPER_COURTS = {"SC", "PC", "FC"}

_SERIES = {"cri": "Cri", "l&s": "L&S", "tax": "Tax"}


@dataclass(frozen=True)
class Citation:
    reporter: str  # SCC, AIR, SCR, SCALE, JT or INSC
    year: int
    page: int  # the judgment number for INSC
    volume: int | None = None
    court: str | None = None  # AIR only
    series: str | None = None  # SCC only: Cri, L&S or Tax
    supplement: bool = False

    @property
    def canonical(self) -> str:
        y, v, p = self.year, self.volume, self.page
        match self.reporter:
            case "SCC":
                series = f" ({self.series})" if self.series else ""
                if self.supplement:
                    return f"{y} Supp ({v}) SCC{series} {p}"
                return f"({y}) {v} SCC{series} {p}"
            case "AIR":
                return f"AIR {y} {self.court} {p}"
            case "SCR":
                vol = f"({v}) " if self.supplement and v else (f"{v} " if v else "")
                supp = "Supp " if self.supplement else ""
                return f"[{y}] {supp}{vol}SCR {p}"
            case "SCALE":
                return f"({y}) {v} SCALE {p}"
            case "JT":
                return f"JT {y} ({v}) SC {p}"
            case "INSC":
                return f"{y} INSC {p}"
        raise ValueError(f"unknown reporter {self.reporter}")

    @property
    def reporter_key(self) -> str:
        """Groups citations that should agree across sources: a case has at
        most one citation per key."""
        if self.reporter == "SCC" and self.series:
            return f"SCC ({self.series})"
        if self.reporter == "AIR":
            return f"AIR {self.court}"
        return self.reporter

    def __str__(self) -> str:
        return self.canonical


_YEAR = r"(?<!\d)(?:\((?P<py>\d{4})\)|(?P<by>\d{4}))\s*"

_PATTERNS: dict[str, re.Pattern[str]] = {
    "SCC": re.compile(
        _YEAR + r"(?P<supp>Supp\s*)?\(?(?P<vol>\d{1,2})\)?\s*SCC"
        r"(?:\s*\((?P<series>Cri|L\s*&\s*S|Tax)\))?\s+(?P<page>\d{1,5})\b",
        re.I,
    ),
    "AIR": re.compile(r"\bAIR\s*(?P<by>\d{4})\s+(?P<court>[A-Za-z]{2,10})\s+(?P<page>\d{1,5})\b", re.I),
    "SCR": re.compile(
        _YEAR + r"(?:(?P<supp>Supp)\s*)?(?:\(?(?P<vol>\d{1,2})\)?\s*)?SCR\s+(?P<page>\d{1,5})\b",
        re.I,
    ),
    "SCALE": re.compile(r"\((?P<py>\d{4})\)\s*(?P<vol>\d{1,2})\s*SCALE\s+(?P<page>\d{1,5})\b", re.I),
    "JT": re.compile(r"\bJT\s*(?P<by>\d{4})\s*\((?P<vol>\d{1,2})\)\s*SC\s+(?P<page>\d{1,5})\b", re.I),
    "INSC": re.compile(r"(?<!\d)(?P<by>\d{4})\s*INSC\s+(?P<page>\d{1,5})\b", re.I),
}


def prepare(text: str) -> str:
    """Normalise punctuation so "S.C.C." reads as "SCC" and "[1967]" as "(1967)"."""
    text = text.replace("[", "(").replace("]", ")")
    text = re.sub(r"(?<=[A-Za-z])\.", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _build(reporter: str, m: re.Match[str]) -> Citation:
    g = m.groupdict()
    year = int(g.get("py") or g.get("by"))
    vol = int(g["vol"]) if g.get("vol") else None
    court = None
    if reporter == "AIR":
        raw = g["court"]
        court = raw.upper() if raw.upper() in _UPPER_COURTS else raw.capitalize()
    series = None
    if g.get("series"):
        series = _SERIES[re.sub(r"\s+", "", g["series"]).lower()]
    return Citation(
        reporter=reporter,
        year=year,
        page=int(g["page"]),
        volume=vol,
        court=court,
        series=series,
        supplement=bool(g.get("supp")),
    )


def scan(prepared: str) -> list[tuple[int, int, Citation]]:
    """All citations in already-`prepare`d text, as (start, end, citation)."""
    found: list[tuple[int, int, Citation]] = []
    for reporter, pattern in _PATTERNS.items():
        for m in pattern.finditer(prepared):
            found.append((m.start(), m.end(), _build(reporter, m)))
    found.sort(key=lambda f: (f[0], -(f[1] - f[0])))
    kept: list[tuple[int, int, Citation]] = []
    for start, end, cit in found:
        if kept and start < kept[-1][1]:
            continue
        kept.append((start, end, cit))
    return kept


def find_citations(text: str) -> list[Citation]:
    return [c for _, _, c in scan(prepare(text))]


def parse_citation(text: str) -> Citation | None:
    """Parse a string that is exactly one citation, or return None."""
    prepared = prepare(text)
    found = scan(prepared)
    if len(found) == 1 and found[0][0] == 0 and found[0][1] == len(prepared):
        return found[0][2]
    return None


def plausibility_issues(cit: Citation, today: date | None = None) -> list[str]:
    """Reasons the citation cannot refer to a real Supreme Court report."""
    today = today or date.today()
    issues = []
    if cit.year > today.year:
        issues.append(f"{cit.year} is in the future")
    supreme_court = cit.reporter != "AIR" or cit.court == "SC"
    first = REPORTER_FIRST_YEAR.get(cit.reporter, SC_FOUNDED)
    if supreme_court and cit.year < first:
        name = "AIR SC" if cit.reporter == "AIR" else cit.reporter
        issues.append(f"{name} has no Supreme Court reports before {first}")
    if cit.page == 0:
        issues.append("page number cannot be 0")
    if cit.volume == 0:
        issues.append("volume number cannot be 0")
    return issues
