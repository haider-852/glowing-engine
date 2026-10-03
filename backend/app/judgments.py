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
  starting "SIKRI, C.J.—The facts are ...", "MAHAJAN J.-This is ..." or, with
  no dash, "CHANDRACHUD, C. J. The petitioners ...".

Anything the splitter is unsure about goes into `warnings`, so a person can
check the judgment before a brief is written from it.

The input is cleaned text (after PDF extraction or OCR). For Digital SCR
PDFs, `scr.clean_scr` produces it; the samples in tests/fixtures/scr are the
real judgments these patterns were tuned on.
"""

from __future__ import annotations

import re
from collections import Counter
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
# "The Judgment of the Court was delivered by", "The following Order of the
# Court was passed:". "of" is often OCR'd ("o£").
_DELIVERED_BY = re.compile(
    r"^the (?:following )?(?:judgments?|order|opinion)\*? \S{1,3} the court (?:was|were) "
    r"(?:delivered|passed|pronounced)(?: by)?\s*[:.\-]*\s*(?P<rest>.*)$",
    re.I,
)
_JUDGE_TITLE = r"(?:C\.?\s*J\.?(?:\s*I\.?)?|JJ?\.?)"
# A judge's name: one to eight capitalised words ("D.Y. CHANDRACHUD",
# "Dr Dhananjaya Y Chandrachud"). Requiring every word to be capitalised keeps
# ordinary sentences ending in ", J." from being read as author lines. ":" and
# "~" are OCR errors inside names in scanned reports ("AYYA:XGAR").
_NAME = r"(?P<name>(?:[A-Z][A-Za-z.'\-:~]*\s*){1,8}?)"
# "D.Y. CHANDRACHUD, J." on its own line.
_AUTHOR_LINE = re.compile(rf"^(?:PER\s+)?{_NAME},\s*{_JUDGE_TITLE}\s*[:.\-—–]*\s*$")
# "SIKRI, C.J.—The facts ...", "MAHAJAN J.-This is ..." (older reports).
_AUTHOR_INLINE = re.compile(rf"^{_NAME},?\s*{_JUDGE_TITLE}\s*[—–\-]+\s*(?P<rest>\S.*)$")
# "CHANDRACHUD, C. J. The petitioners ...", "DR. ANAND, J. This appeal ...":
# no dash, so the name must be in capitals and followed by a comma.
_AUTHOR_INLINE_CAPS = re.compile(
    rf"^(?P<name>(?:DR\.?\s+)?[A-Z][A-Z.'\-]+(?:\s+[A-Z][A-Z.'\-]+){{0,6}}),\s*{_JUDGE_TITLE}\s+(?P<rest>[A-Z\"“].*)$"
)
# "...........................J." and the bracketed name under it.
_SIGNATURE = re.compile(rf"^\.{{3,}}\s*,?\s*{_JUDGE_TITLE}\s*$")
_SIGNATURE_NAME = re.compile(r"^[\[(]\s*[A-Z][A-Z.\s'\-]+[\])]\s*$")
_PLACE_DATE = re.compile(
    r"^(new delhi[;,.]?|(january|february|march|april|may|june|july|august|september|october|november|december)"
    r"\s+\d{1,2},\s*\d{4}\.?)$",
    re.I,
)
# "12. The appellant ...", "12.3 The appellant ...", "12 The appellant ..."
# and the typo "12 .The appellant".
_NUMBERED = re.compile(r"^(?P<num>\d{1,4}(?:\.\d{1,3})*)(?:(?P<dot>\s?\.)(?:\s+|(?=[A-Z\"“(]))|\s+)(?P<rest>\S.*)$")
# A paragraph number alone on its line, as plain pdftotext output gives it.
_NUMBER_ALONE = re.compile(r"^\s*\d{1,3}(?:\.\d{1,3})*\.\s*$")

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
    def __init__(self, words: Counter[str]) -> None:
        self.words = words  # the judgment's vocabulary, for line-break hyphens
        self.header: list[str] = []
        self.opinions: list[Opinion] = []
        self.paragraphs: list[Paragraph] = []
        self.warnings: list[str] = []
        self.blocks: list[list[str]] = []  # blocks of the paragraph being built
        self.court_number: str | None = None
        self.last_top: int | None = None  # last top-level number in this opinion
        self.dotted: bool | None = None  # whether this opinion writes "1." or "1"
        self.pending_opinion = False
        self.in_trailer = False
        self.prev_blank = True
        self.last_line = ""

    # Paragraph assembly

    def flush(self) -> None:
        blocks = [" ".join(b) for b in self.blocks if b]
        text = "\n\n".join(_join_hyphens(b, self.words) for b in blocks).strip()
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
        self.dotted = None
        self.pending_opinion = False
        self.in_trailer = False

    # Numbering

    def accept_number(self, num: str, has_dot: bool) -> bool:
        parts = [int(x) for x in num.split(".")]
        top = parts[0]
        if len(parts) > 1:  # "23.1": a sub-paragraph of the current paragraph
            return self.last_top == top
        if self.dotted is not None and has_dot != self.dotted:
            return False
        if not has_dot and not self.prev_blank:
            # "1 The order ..." numbering is accepted only at a paragraph
            # break: wrapped text often starts with a number ("5 of the Act").
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
        if boundary and ((m := _AUTHOR_INLINE.match(line)) or (m := _AUTHOR_INLINE_CAPS.match(line))):
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
                self.dotted = bool(m["dot"])
            self.start_paragraph(m["rest"], m["num"])
            return
        self.add_line(line)

    def finish(self, lines: list[str]) -> SplitJudgment:
        self.flush()
        if not self.opinions:
            # No opinion markers anywhere: the whole text is one opinion.
            fresh = _Splitter(self.words)
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


# Prefixes that keep their hyphen at a line break when the judgment gives no
# evidence either way. "re" is not one: typesetters break "re-spondent".
_HYPHEN_PREFIXES = frozenset("non self quasi cross counter ex co semi multi well ill".split())
# Short words that join a compound chain ("case-by-case", "son-in-law").
_CHAIN_WORDS = frozenset("by in of to and on".split())
# Words that start one-word forms more often than compounds ("notwithstanding", "overruled").
_JOINING_HEADS = frozenset("not per for any out with over under there where here".split())
# Word endings that are never the second half of a compound.
_SUFFIXES = frozenset("ing ed ly wise ment tion sion ness able ible ful ive ity ance ence".split())
_LINE_BREAK_HYPHEN = re.compile(r"(?<![\w-])([\w-]*?)(\w+)- (\w[\w'’-]*)")
_EDGE_PUNCTUATION = ".,;:!?\"'“”‘’()[]{}*"


def _vocabulary(lines: list[str]) -> Counter[str]:
    """Lower-cased words of the judgment, leaving out each line's last word
    when it ends in a hyphen: that hyphen may only be a line break."""
    words: Counter[str] = Counter()
    for line in lines:
        tokens = line.split()
        if tokens and tokens[-1].endswith("-"):
            tokens = tokens[:-1]
        words.update(w for t in tokens if (w := t.strip(_EDGE_PUNCTUATION).lower()))
    return words


def _join_hyphens(text: str, words: Counter[str]) -> str:
    """Rejoin words split across lines ("Govern- ment"), keeping the hyphen of
    a real compound ("self- defence", "Munsif- Magistrate").

    The judgment itself is the evidence: whichever of "government" and
    "govern-ment" it uses elsewhere wins, first as the whole word
    ("non-agri- cultural" against "non-agricultural") and then as the two
    halves either side of the break. With no evidence, the hyphen stays after
    a compound prefix, or between two words the judgment uses on their own
    ("subject- matter"), and goes otherwise ("contri- buted").
    """

    def fix(m: re.Match[str]) -> str:
        before, head, rest = m[1], m[2], m[3]
        tail = rest.split("-")[0]
        whole = rest.strip(_EDGE_PUNCTUATION)
        if not tail[0].islower() or head[-1].isdigit():
            keep = True  # "Munsif- Magistrate", "9- A"
        elif (a := words[f"{before}{head}{whole}".lower()]) + (b := words[f"{before}{head}-{whole}".lower()]):
            keep = b > a
        elif (a := words[(head + tail).lower()]) + (b := words[f"{head}-{tail}".lower()]):
            keep = b > a
        elif tail.lower() in _SUFFIXES:
            keep = False
        else:
            h, t = head.lower(), tail.lower()
            both_words = len(h) > 2 and len(t) > 2 and words[h] > 0 and words[t] > 0 and h not in _JOINING_HEADS
            chain = bool(before) and h in _CHAIN_WORDS
            keep = h in _HYPHEN_PREFIXES or both_words or chain or ("-" in rest and not before)
        return f"{before}{head}-{rest}" if keep else before + head + rest

    return _LINE_BREAK_HYPHEN.sub(fix, text)


def _join_lone_numbers(lines: list[str]) -> list[str]:
    """Put a paragraph number that sits alone on its line ("1.") in front of
    the text that follows it."""
    out: list[str] = []
    carry: str | None = None
    for line in lines:
        if carry is not None:
            if not line.strip():
                continue
            out.append(f"{carry} {line.strip()}")
            carry = None
        elif _NUMBER_ALONE.match(line):
            carry = line.strip()
        else:
            out.append(line)
    if carry is not None:
        out.append(carry)
    return out


def split_judgment(text: str) -> SplitJudgment:
    lines = _join_lone_numbers(text.replace("\r\n", "\n").replace("\f", "\n").split("\n"))
    splitter = _Splitter(_vocabulary(lines))
    for line in lines:
        splitter.feed(line)
    return splitter.finish(lines)
