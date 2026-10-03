"""Turn what the user typed into one case, a short list, or nothing.

Resolving a name is not verifying a case. The resolver only says which entry
in our table the user most likely meant; verification against the sources
happens afterwards. When in doubt the resolver asks ("Did you mean…?") rather
than picking.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from .cases import CaseEntry
from .citations import Citation, plausibility_issues, prepare, scan
from .text import TOKEN_MATCH, best_token_scores, coverage, distinctive_tokens

# A case is a firm match only if every distinctive word in the query matches
# it, and the query covers at least this share of one of its names.
MIN_NAME_COVERAGE = 0.5
# Below this, a candidate is not even worth suggesting.
MIN_SUGGESTION_SCORE = 0.4
# If two firm matches score within this margin, ask the user to choose.
AMBIGUITY_MARGIN = 0.1
MAX_SUGGESTIONS = 5

_YEAR = re.compile(r"(?<!\d)(19[5-9]\d|20\d\d)(?!\d)")


class ResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"  # several cases fit: ask the user to choose
    SUGGESTIONS = "suggestions"  # nothing fits firmly: "Did you mean…?"
    NOT_FOUND = "not_found"
    INVALID_CITATION = "invalid_citation"


@dataclass
class Candidate:
    case: CaseEntry
    score: float
    notes: list[str] = field(default_factory=list)


@dataclass
class Resolution:
    query: str
    status: ResolutionStatus
    candidates: list[Candidate] = field(default_factory=list)
    message: str = ""
    citations: list[Citation] = field(default_factory=list)

    @property
    def case(self) -> CaseEntry | None:
        return self.candidates[0].case if self.status is ResolutionStatus.RESOLVED else None


@dataclass
class _Match:
    case: CaseEntry
    score: float
    firm: bool


class Resolver:
    def __init__(self, cases: list[CaseEntry]):
        self.cases = cases
        self._by_id = {c.id: c for c in cases}
        self._by_citation = {cit.canonical: c for c in cases for cit in c.citations}

    def get(self, case_id: str) -> CaseEntry | None:
        return self._by_id.get(case_id)

    def resolve(self, query: str) -> Resolution:
        prepared = prepare(query)
        found = scan(prepared)
        remainder = prepared
        for start, end, _ in reversed(found):
            remainder = remainder[:start] + " " + remainder[end:]
        citations = [c for _, _, c in found]
        words = distinctive_tokens(remainder)
        years = {int(y) for y in _YEAR.findall(remainder)}

        if citations:
            return self._resolve_citations(query, citations, words)
        if not words:
            return Resolution(
                query,
                ResolutionStatus.NOT_FOUND,
                message="The query has no distinctive words to search on. Try a party name or a citation.",
            )
        return self._resolve_name(query, words, years)

    def _resolve_citations(self, query: str, citations: list[Citation], words: list[str]) -> Resolution:
        for cit in citations:
            if issues := plausibility_issues(cit):
                return Resolution(
                    query,
                    ResolutionStatus.INVALID_CITATION,
                    message=f"{cit.canonical} cannot be a real Supreme Court citation: {'; '.join(issues)}.",
                    citations=citations,
                )

        matched = {
            self._by_citation[c.canonical].id: self._by_citation[c.canonical]
            for c in citations
            if c.canonical in self._by_citation
        }
        if not matched:
            return Resolution(
                query,
                ResolutionStatus.NOT_FOUND,
                message="This citation is not in our table yet. That does not mean the case does not exist; "
                "check it on the official sources.",
                citations=citations,
            )
        if len(matched) > 1:
            return Resolution(
                query,
                ResolutionStatus.AMBIGUOUS,
                [Candidate(c, 1.0, ["citations in the query point to different cases"]) for c in matched.values()],
                message="The citations you entered point to different cases.",
                citations=citations,
            )

        case = next(iter(matched.values()))
        unknown = [c.canonical for c in citations if c.canonical not in self._by_citation]
        if unknown:
            return Resolution(
                query,
                ResolutionStatus.SUGGESTIONS,
                [Candidate(case, 1.0, [f"not one of its citations: {', '.join(unknown)}"])],
                message="Some citations you entered do not belong to this case.",
                citations=citations,
            )
        if words and not self._score(case, words).firm:
            return Resolution(
                query,
                ResolutionStatus.SUGGESTIONS,
                [Candidate(case, 1.0, ["the name in the query does not match this citation"])],
                message="The citation and the case name point to different cases.",
                citations=citations,
            )
        return Resolution(query, ResolutionStatus.RESOLVED, [Candidate(case, 1.0)], citations=citations)

    def _score(self, case: CaseEntry, words: list[str]) -> _Match:
        # Query words may come from the title and from aliases together
        # ("Puttaswamy privacy"), so match them against all the case's names.
        pool = [t for name in case.name_tokens for t in name]
        word_scores = best_token_scores(words, pool)
        query_cov = sum(word_scores) / len(word_scores)
        all_words_match = all(s >= TOKEN_MATCH for s in word_scores)
        name_cov = max((coverage(list(name), words) for name in case.name_tokens if name), default=0.0)
        score = 0.7 * query_cov + 0.3 * name_cov
        return _Match(case, score, all_words_match and name_cov >= MIN_NAME_COVERAGE)

    def _resolve_name(self, query: str, words: list[str], years: set[int]) -> Resolution:
        matches = [self._score(c, words) for c in self.cases]
        matches = [m for m in matches if m.score >= MIN_SUGGESTION_SCORE]
        matches.sort(key=lambda m: (m.score, m.case.cited_by_count or 0), reverse=True)

        notes: dict[str, list[str]] = {m.case.id: [] for m in matches}
        firm = []
        for m in matches:
            if years and not (years & m.case.years):
                notes[m.case.id].append(
                    f"you entered {', '.join(map(str, sorted(years)))}; this case is from {m.case.year}"
                )
            elif m.firm:
                firm.append(m)

        def candidates(ms: list[_Match]) -> list[Candidate]:
            return [Candidate(m.case, round(m.score, 3), notes[m.case.id]) for m in ms[:MAX_SUGGESTIONS]]

        if len(firm) == 1 or (len(firm) > 1 and firm[0].score - firm[1].score >= AMBIGUITY_MARGIN):
            return Resolution(query, ResolutionStatus.RESOLVED, candidates(firm[:1]))
        if firm:
            close = [m for m in firm if firm[0].score - m.score < AMBIGUITY_MARGIN]
            return Resolution(
                query,
                ResolutionStatus.AMBIGUOUS,
                candidates(close),
                message="Several cases match. Which one did you mean?",
            )
        if matches:
            return Resolution(
                query,
                ResolutionStatus.SUGGESTIONS,
                candidates(matches),
                message="No case matches exactly. Did you mean one of these?",
            )
        return Resolution(
            query,
            ResolutionStatus.NOT_FOUND,
            message="No case in our table matches. That does not mean the case does not exist; "
            "check it on the official sources.",
        )
