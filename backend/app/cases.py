"""The alias table: what the resolver knows about each case.

In production this lives in Postgres (cases, case_aliases, citations). For now
it loads from a YAML file so it can be edited by hand and reviewed in git.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .citations import Citation, parse_citation, plausibility_issues
from .text import distinctive_tokens

DEFAULT_SEED = Path(__file__).resolve().parent.parent / "data" / "seed_cases.yaml"


@dataclass(frozen=True)
class CaseEntry:
    id: str
    title: str
    year: int  # year of decision
    aliases: tuple[str, ...] = ()
    citations: tuple[Citation, ...] = ()
    bench_strength: int | None = None
    cited_by_count: int | None = None
    # False until a person has checked the entry against an official source.
    checked_against_source: bool = False
    name_tokens: tuple[tuple[str, ...], ...] = field(default=(), compare=False, repr=False)

    @property
    def names(self) -> tuple[str, ...]:
        return (self.title, *self.aliases)

    @property
    def years(self) -> set[int]:
        """Years a user might reasonably type: the decision year, plus the
        year of each report (Koushal was decided in 2013, reported in 2014)."""
        return {self.year} | {c.year for c in self.citations}


class CaseTableError(ValueError):
    pass


def load_cases(path: Path = DEFAULT_SEED) -> list[CaseEntry]:
    raw = yaml.safe_load(path.read_text())
    entries: list[CaseEntry] = []
    seen_ids: set[str] = set()
    seen_citations: dict[str, str] = {}
    for row in raw["cases"]:
        case_id = row["id"]
        if case_id in seen_ids:
            raise CaseTableError(f"duplicate case id {case_id}")
        seen_ids.add(case_id)

        citations = []
        for text in row.get("citations", []):
            cit = parse_citation(text)
            if cit is None:
                raise CaseTableError(f"{case_id}: cannot parse citation {text!r}")
            if issues := plausibility_issues(cit):
                raise CaseTableError(f"{case_id}: {text!r}: {'; '.join(issues)}")
            if cit.canonical in seen_citations:
                other = seen_citations[cit.canonical]
                raise CaseTableError(f"{cit.canonical} is listed for both {other} and {case_id}")
            seen_citations[cit.canonical] = case_id
            citations.append(cit)

        keys = [c.reporter_key for c in citations]
        if len(keys) != len(set(keys)):
            raise CaseTableError(f"{case_id}: more than one citation in the same reporter")

        aliases = tuple(row.get("aliases", []))
        entries.append(
            CaseEntry(
                id=case_id,
                title=row["title"],
                year=int(row["year"]),
                aliases=aliases,
                citations=tuple(citations),
                bench_strength=row.get("bench_strength"),
                cited_by_count=row.get("cited_by_count"),
                checked_against_source=bool(row.get("checked_against_source", False)),
                name_tokens=tuple(tuple(distinctive_tokens(n)) for n in (row["title"], *aliases)),
            )
        )
    return entries
