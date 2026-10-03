"""Split a judgment's text into opinions and paragraphs.

Every paragraph gets our own `ordinal` (1..n across the whole judgment), which
is what briefs cite. `court_number` is kept only when the court's own text
numbers the paragraph. We never take numbering from a publisher's edition
(EBC v. D.B. Modak).

Handles the two layouts most SC judgments use:

* modern judgments: "J U D G M E N T", an author line ("D.Y. CHANDRACHUD, J."),
  paragraphs numbered "1.", "2.", "23.1", numbering restarting in each
  separate opinion, and signature blocks;
* older reports: unnumbered paragraphs separated by blank lines, opinions
  starting "SIKRI, C.J.—The facts are ...".

Anything the splitter is unsure about goes into `warnings`, so a person can
check the judgment before a brief is written from it.

The input is cleaned text (after PDF extraction or OCR). Tune the patterns on
real judgments before relying on them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Lines that are page furniture, not judgment text.
_NOISE = [
    re.compile(p, re.I)
    for p in (
        r"^\d{1,4}$",
        r"^page \d+ of \d+$",
        r"^-\s*\d+\s*-$",
        r"^signature not verified$",
        r"^digitally signed by\b.*",
        r"^date:\s*\d{4}[.\-]\d{2}[.\-]\d{2}.*",
        r"^reason:.*",
        r"^(non-)?reportable$",
    )
]

_HEADING = re.compile(r"^(?:J\s*U\s*D\s*G\s*M\s*E\s*N\s*T|O\s*R\s*D\s*E\s*R)\s*$", re.I)
_DELIVERED_BY = re.compile(r"^the (?:judgment|order) of the court was delivered by\s*:?\s*(?P<rest>.*)$", re.I)
_JUDGE_TITLE = r"(?:C\.?\s*J\.?(?:\s*I\.?)?|JJ?\.?)"
# A judge's name: one to eight capitalised words ("D.Y. CHANDRACHUD",
# "Dr Dhananjaya Y Chandrachud"). Requiring every word to be capitalised keeps
# ordinary sentences ending in ", J." from being read as author lines.
_NAME = r"(?P<name>(?:[A-Z][A-Za-z.'\-]*\s*){1,8}?)"
# "D.Y. CHANDRACHUD, J." on its own line.
_AUTHOR_LINE = re.compile(rf"^(?:PER\s+)?{_NAME},\s*{_JUDGE_TITLE}\s*[:.\-—–]*\s*$")
# "SIKRI, C.J.—The facts ..." (older reports).
_AUTHOR_INLINE = re.compile(rf"^{_NAME},\s*{_JUDGE_TITLE}\s*[—–]+\s*(?P<rest>\S.*)$")
# "...........................J." and the bracketed name under it.
_SIGNATURE = re.compile(rf"^\.{{3,}}\s*,?\s*{_JUDGE_TITLE}\s*$")
_SIGNATURE_NAME = re.compile(r"^[\[(]\s*[A-Z][A-Z.\s'\-]+[\])]\s*$")
_PLACE_DATE = re.compile(
    r"^(new delhi[;,.]?|(january|february|march|april|may|june|july|august|september|october|november|december)"
    r"\s+\d{1,2},\s*\d{4}\.?)$",
    re.I,
)
# "12. The appellant ..." or "12.3 The appellant ..."
_NUMBERED = re.compile(r"^(?P<num>\d{1,4}(?:\.\d{1,3})*)(?P<dot>\.)?\s+(?P<rest>\S.*)$")

MAX_NUMBER_GAP = 5


@dataclass
class Opinion:
    index: int
    authors: list[str] = field(default_factory=list)


@dataclass
class Paragraph:
    ordinal: int
    opinion: int
    text: str
    court_number: str | None = None


@dataclass
class SplitJudgment:
    header: str
    opinions: list[Opinion]
    paragraphs: list[Paragraph]
    warnings: list[str]

    def paragraph(self, ordinal: int) -> Paragraph | None:
        if 1 <= ordinal <= len(self.paragraphs):
            return self.paragraphs[ordinal - 1]
        return None

    def label(self, p: Paragraph) -> str:
        """How to show a reference: the court's number with the author when
        there is one, otherwise our own number."""
        if p.court_number is None:
            return f"[{p.ordinal}]"
        authors = self.opinions[p.opinion].authors
        if len(self.opinions) > 1 and authors:
            return f"{_short_name(authors[0])}, para {p.court_number}"
        return f"para {p.court_number}"


def _short_name(name: str) -> str:
    return name.split()[-1].title() + " J."


def _clean_author(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip(" .")


class _Splitter:
    def __init__(self) -> None:
        self.header: list[str] = []
        self.opinions: list[Opinion] = []
        self.paragraphs: list[Paragraph] = []
        self.warnings: list[str] = []
        self.blocks: list[list[str]] = []  # blocks of the paragraph being built
        self.court_number: str | None = None
        self.last_top: int | None = None  # last top-level number in this opinion
        self.pending_opinion = False
        self.in_trailer = False
        self.prev_blank = True
        self.last_line = ""

    # Paragraph assembly

    def flush(self) -> None:
        blocks = [" ".join(b) for b in self.blocks if b]
        text = "\n\n".join(_join_hyphens(b) for b in blocks).strip()
        if text:
            if not self.opinions:
                self.opinions.append(Opinion(0))
            self.paragraphs.append(Paragraph(len(self.paragraphs) + 1, len(self.opinions) - 1, text, self.court_number))
        self.blocks = []
        self.court_number = None

    def start_paragraph(self, first_line: str, court_number: str | None) -> None:
        self.flush()
        self.court_number = court_number
        self.blocks = [[first_line]]

    def add_line(self, line: str) -> None:
        if not self.blocks:
            self.blocks = [[]]
        self.blocks[-1].append(line)

    def blank(self) -> None:
        if self.court_number is not None:
            # Numbered paragraphs often contain block quotes; a blank line
            # does not end the paragraph.
            if self.blocks and self.blocks[-1]:
                self.blocks.append([])
        else:
            self.flush()

    def start_opinion(self, authors: list[str]) -> None:
        self.flush()
        self.opinions.append(Opinion(len(self.opinions), authors))
        self.last_top = None
        self.pending_opinion = False
        self.in_trailer = False

    # Numbering

    def accept_number(self, num: str, has_dot: bool) -> bool:
        parts = [int(x) for x in num.split(".")]
        top = parts[0]
        if len(parts) > 1:  # "23.1": a sub-paragraph of the current paragraph
            return self.last_top == top
        if not has_dot:
            return False
        if self.last_top is None:
            if top == 1:
                return True
            if top <= MAX_NUMBER_GAP:
                self.warnings.append(f"Opinion {len(self.opinions)}: numbering starts at {top}, not 1.")
                return True
            return False
        if top == self.last_top + 1:
            return True
        if self.last_top < top <= self.last_top + MAX_NUMBER_GAP:
            self.warnings.append(
                f"Opinion {len(self.opinions)}: numbering jumps from {self.last_top} to {top}; "
                "paragraphs may be missing."
            )
            return True
        return False

    def at_opinion_boundary(self) -> bool:
        """Whether an author line here can start a new opinion, rather than
        being a judge's name that happens to end a wrapped line of text."""
        if self.pending_opinion or self.in_trailer or not self.opinions:
            return True
        return self.prev_blank and (not self.last_line or self.last_line[-1] in '.:"\u201d)')

    # Main loop

    def feed(self, raw: str) -> None:
        line = raw.strip()
        if not line:
            self.blank()
            self.prev_blank = True
            return
        if any(p.match(line) for p in _NOISE):
            return
        self._feed(line, raw)
        self.prev_blank = False
        self.last_line = line

    def _feed(self, line: str, raw: str) -> None:
        if _SIGNATURE.match(line):
            self.flush()
            self.in_trailer = True
            return
        if self.in_trailer and (_SIGNATURE_NAME.match(line) or _PLACE_DATE.match(line)):
            return

        if _HEADING.match(line):
            self.flush()
            self.pending_opinion = True
            return
        if m := _DELIVERED_BY.match(line):
            self.flush()
            self.pending_opinion = True
            if not m["rest"]:
                return
            line = m["rest"]
        boundary = self.at_opinion_boundary()
        if boundary and (m := _AUTHOR_LINE.match(line)):
            self.start_opinion([_clean_author(m["name"])])
            return
        if boundary and (m := _AUTHOR_INLINE.match(line)):
            self.start_opinion([_clean_author(m["name"])])
            self.start_paragraph(m["rest"], None)
            return

        if self.pending_opinion:
            self.start_opinion([])
        if not self.opinions:
            # Before any opinion marker: cause title and preamble, unless the
            # judgment turns out to have no markers at all (see finish()).
            self.header.append(raw.rstrip())
            return
        self.in_trailer = False

        if (m := _NUMBERED.match(line)) and self.accept_number(m["num"], bool(m["dot"])):
            if "." not in m["num"]:
                self.last_top = int(m["num"])
            self.start_paragraph(m["rest"], m["num"])
            return
        self.add_line(line)

    def finish(self, lines: list[str]) -> SplitJudgment:
        self.flush()
        if not self.opinions:
            # No opinion markers anywhere: the whole text is one opinion.
            fresh = _Splitter()
            fresh.start_opinion([])
            for line in lines:
                fresh.feed(line)
            fresh.flush()
            fresh.warnings.insert(0, "No judgment heading or author line found; treated the text as one opinion.")
            return SplitJudgment("", fresh.opinions, fresh.paragraphs, fresh.warnings)

        for op in self.opinions:
            paras = [p for p in self.paragraphs if p.opinion == op.index]
            if not paras:
                self.warnings.append(f"Opinion {op.index + 1} has no text.")
            elif all(p.court_number is None for p in paras):
                self.warnings.append(
                    f"Opinion {op.index + 1} has no court paragraph numbers; references use our own numbering."
                )
        header = "\n".join(self.header).strip()
        return SplitJudgment(header, self.opinions, self.paragraphs, self.warnings)


def _join_hyphens(text: str) -> str:
    # "self- defence" from a line break becomes "self-defence". A word split
    # across lines ("inter- est") keeps its hyphen; we cannot tell the two apart.
    return re.sub(r"(\w)- (\w)", r"\1-\2", text)


def split_judgment(text: str) -> SplitJudgment:
    lines = text.replace("\r\n", "\n").replace("\f", "\n").split("\n")
    splitter = _Splitter()
    for line in lines:
        splitter.feed(line)
    return splitter.finish(lines)
