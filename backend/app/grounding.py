"""Check a generated brief against the judgment it was written from.

Every claim in a brief must stand on the judgment's own text. A claim is
dropped when:

* it cites no paragraph, or a paragraph that does not exist;
* a quotation in it does not appear word for word in the cited paragraphs;
* it names a case, or gives a citation, that is not in the cited paragraphs.
  The judgment under brief is the exception: the brief may always name it.

A claim is kept but flagged when it names a case that is in the cited
paragraphs but not yet in our case table (roadmap: "Every case named in a
brief must match a record in the database, or it is flagged").

This catches invented quotations, paragraph numbers and cases. Whether a
paragraph actually supports a claim's meaning needs a separate model check
(the roadmap's 98% target), which is not done here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .cases import CaseEntry
from .citations import find_citations
from .judgments import SplitJudgment
from .resolver import Resolver
from .text import SKELETON_MATCH, coverage, distinctive_tokens, titles_match

BRIEF_SECTIONS = ("facts", "issues", "arguments", "holding", "ratio", "obiter", "opinions")

# How closely a case name in a brief must match the words of the cited
# paragraphs to count as coming from them. Stricter than name search, because
# a paragraph has many words for a made-up name to brush against.
NAME_GROUNDING_MATCH = SKELETON_MATCH
NAME_GROUNDING_COVERAGE = 0.8

_PUNCT = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-"})
_ELLIPSIS = re.compile(r"\s*(?:\[\s*\.\.\.\s*\]|\.\.\.)\s*")
_QUOTED = re.compile(r'"([^"]+)"')
_VERSUS = re.compile(r"\s+(?:v|vs|versus)\.?\s+")
_CONNECTORS = {"of", "and", "&", "the", "for"}
_LEAD_WORDS = {
    "in",
    "see",
    "the",
    "as",
    "following",
    "per",
    "cf",
    "also",
    "while",
    "unlike",
    "like",
    "after",
    "before",
    "under",
    "this",
    "that",
    "and",
    "of",
    "for",
}
_MAX_PARTY_WORDS = 10
# A full stop after these does not end a sentence.
_ABBREVIATION = re.compile(r"(?:[A-Z]\.)+|(?:Ltd|Anr|Ors|Co|Pvt|Retd|Dr|Mr|Mrs|Smt|Bros|Mohd|Jt|St)\.", re.I)


@dataclass
class Claim:
    section: str
    text: str
    paragraphs: list[int]  # paragraph ordinals in the split judgment


@dataclass
class ClaimCheck:
    claim: Claim
    problems: list[str] = field(default_factory=list)  # any problem drops the claim
    flags: list[str] = field(default_factory=list)  # kept, but a person should look

    @property
    def kept(self) -> bool:
        return not self.problems


@dataclass
class GroundingReport:
    checks: list[ClaimCheck]

    @property
    def kept(self) -> list[Claim]:
        return [c.claim for c in self.checks if c.kept]

    @property
    def dropped(self) -> list[ClaimCheck]:
        return [c for c in self.checks if not c.kept]

    @property
    def flagged(self) -> list[ClaimCheck]:
        return [c for c in self.checks if c.kept and c.flags]

    def sections(self) -> dict[str, list[Claim]]:
        out: dict[str, list[Claim]] = {s: [] for s in BRIEF_SECTIONS}
        for claim in self.kept:
            out.setdefault(claim.section, []).append(claim)
        return out

    def empty_sections(self) -> list[str]:
        """Sections with nothing left after checking; show "could not verify"."""
        return [s for s, claims in self.sections().items() if not claims]


def normalize_for_quotes(text: str) -> str:
    text = text.translate(_PUNCT).replace("…", "...").replace("­", "")
    return re.sub(r"\s+", " ", text).strip()


def quotations(text: str) -> list[str]:
    return [q.strip() for q in _QUOTED.findall(normalize_for_quotes(text)) if q.strip()]


def quote_in(quote: str, passage: str) -> bool:
    """Whether the quotation appears word for word, allowing "..." to mark
    words left out (the pieces must appear in order)."""
    pos = 0
    for piece in (p for p in _ELLIPSIS.split(quote) if p):
        found = passage.find(piece, pos)
        if found < 0:
            return False
        pos = found + len(piece)
    return True


def case_names(text: str) -> list[str]:
    """Case names written as "X v. Y" in a sentence."""
    names = []
    for m in _VERSUS.finditer(text):
        left = _party(reversed(text[: m.start()].split()), leftward=True)
        right = _party(iter(text[m.end() :].split()), leftward=False)
        if left and right:
            names.append(f"{left} v. {right}")
    return names


def _party(words, leftward: bool) -> str:
    taken: list[str] = []
    for raw in words:
        word = raw.strip(",;:()[]\"'")
        if not word or len(taken) >= _MAX_PARTY_WORDS:
            break
        # Punctuation after a word ends the name: on the left it belongs to
        # the previous clause ("In 1973, Kesavananda v. ..."); on the right
        # the name stops after it ("... v. State of Kerala, the Court").
        if leftward and taken and raw[-1] in ",;:":
            break
        if not (word[0].isupper() or word.lower() in _CONNECTORS):
            break
        taken.append(word)
        if not leftward and (raw[-1] in ",;:)" or (raw.endswith(".") and not _ABBREVIATION.fullmatch(word))):
            break
    if leftward:
        taken.reverse()
        while taken and taken[0].lower() in _LEAD_WORDS:
            taken.pop(0)
    while taken and taken[-1].lower() in _CONNECTORS:
        taken.pop()
    if taken and taken[-1].endswith(".") and not _ABBREVIATION.fullmatch(taken[-1]):
        taken[-1] = taken[-1][:-1]
    return " ".join(taken)


def check_brief(
    claims: list[Claim],
    judgment: SplitJudgment,
    resolver: Resolver | None = None,
    subject: CaseEntry | None = None,
) -> GroundingReport:
    all_texts = [normalize_for_quotes(p.text) for p in judgment.paragraphs]
    return GroundingReport([_check(c, judgment, all_texts, resolver, subject) for c in claims])


def _check(
    claim: Claim,
    judgment: SplitJudgment,
    all_texts: list[str],
    resolver: Resolver | None,
    subject: CaseEntry | None,
) -> ClaimCheck:
    check = ClaimCheck(claim)
    if not claim.text.strip():
        check.problems.append("The claim is empty.")
        return check
    if not claim.paragraphs:
        check.problems.append("The claim cites no paragraph.")
        return check
    missing = [n for n in claim.paragraphs if judgment.paragraph(n) is None]
    if missing:
        check.problems.append(f"Cites paragraphs that do not exist: {missing}.")
        return check

    cited = [all_texts[n - 1] for n in sorted(set(claim.paragraphs))]
    cited_joined = " ".join(cited)

    for quote in quotations(claim.text):
        if any(quote_in(quote, t) for t in cited) or quote_in(quote, cited_joined):
            continue
        elsewhere = [judgment.label(judgment.paragraphs[i]) for i, t in enumerate(all_texts) if quote_in(quote, t)]
        if elsewhere:
            check.problems.append(f"Quotation {quote!r} is in {', '.join(elsewhere)}, not the cited paragraphs.")
        else:
            check.problems.append(f"Quotation {quote!r} does not appear in the judgment.")

    cited_citations = {c.canonical for t in cited for c in find_citations(t)}
    own_citations = {c.canonical for c in subject.citations} if subject else set()
    for cit in find_citations(claim.text):
        if cit.canonical in cited_citations or cit.canonical in own_citations:
            continue
        check.problems.append(f"Citation {cit.canonical} is not in the cited paragraphs.")

    cited_words = distinctive_tokens(cited_joined)
    for name in case_names(normalize_for_quotes(claim.text)):
        if subject and any(titles_match(name, n) for n in subject.names):
            continue
        words = distinctive_tokens(name)
        grounded = bool(words) and (
            coverage(words, cited_words, threshold=NAME_GROUNDING_MATCH) >= NAME_GROUNDING_COVERAGE
        )
        if not grounded:
            check.problems.append(f"Names {name!r}, which is not in the cited paragraphs.")
        elif resolver and resolver.resolve(name).case is None:
            check.flags.append(f"Names {name!r}, which is not in our case table yet.")
    return check
