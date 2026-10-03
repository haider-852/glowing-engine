"""Clean the text of a Digital SCR report before it is split.

Digital SCR PDFs (scr.sci.gov.in, once digiscr.sci.gov.in) are Supreme Court
Reports pages: the judgment is wrapped in the reporter's material, and every
page carries furniture that is not judgment text. This module takes the output
of `pdftotext -layout` and returns the judgment text the splitter expects,
with the rest set aside:

* header: the case title, bench, headnotes, counsel and the "judgment of the
  Court was delivered by" line;
* body: the judgment itself;
* trailer: the editor's disposal line ("Appeal dismissed."), agents, and on
  older volumes the start of the next case;
* footnotes, taken out of the running text.

Removed on every page: running heads ("SUPREME COURT REPORTS", "[2024] 2
S.C.R. 687", "RAM RATTAN v. BAJRANG LAL (Desai, J.)"), page numbers, the A-H
letters SCR prints in the margin to locate passages, and on scanned volumes
the marginal notes (year, case title, judge) beside the text. On the first
page of a scanned volume, the end of the previous case is dropped.

`-layout` is needed: paragraph breaks in SCR are shown by indentation, not
blank lines, and margins can only be told apart from text by position. The
cleaner turns indented first lines into blank-line paragraph breaks.

Tuned on the samples in tests/fixtures/scr. Scanned volumes (roughly before
1970) come with OCR errors that this does not try to correct.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Text runs separated by this many spaces are separate segments of a line:
# body text versus a marginal note or margin letter.
_GAP = re.compile(r"\S+(?: {1,2}\S+)*")

# A segment holding only an SCR margin letter (A-H), maybe with OCR debris.
# "0" is an OCR'd "D"; a lone mark is debris from the scan. Brackets are not
# debris: "(a)" starts a list item.
_MARGIN_LETTER = re.compile(r"^[^\w\s()]{0,2}[A-H0][^\w\s()]{0,2}$|^[^\w\s()]{1,2}$")
# Scans of lettered volumes also read the letter in lower case.
_MARGIN_LETTER_OCR = re.compile(r"^[^\w\s()]{0,2}[a-h][^\w\s()]{0,2}$")
_LEADING_LETTER = re.compile(r"^[A-H]\s(?=\S)")
# B-H are not words: one in front of a lower-case word is a margin letter
# wherever it sits ("B one of the elements").
_LEADING_LETTER_ANYWHERE = re.compile(r"^[B-H]\s(?=[a-z])")
_LEADING_DEBRIS = re.compile(r"^(?:[·•`~]\s+(?=\S)|[.,]\s+(?=[A-Z\"“(]))")
# Typed volumes print the letter one space from the text, even mid-line:
# "... informed A", "he shall not be D remanded".
_INLINE_LETTER = re.compile(r"(?<=[a-z,;]) [A-H](?= [a-z])")
_TRAILING_LETTER = re.compile(r"\s[A-H]$")
_MARGIN_LETTER_STRICT = re.compile(r"^[A-H]$")
# A segment that is a paragraph number hanging left of the text column.
_HANGING_NUMBER = re.compile(r"^\(?[1-9]\d{0,2}(?:\.\d{1,3})*[.)]?$")

# Scans garble the head ("SUPl\\FME CoURT REPORTS", "SUPREME COURt l\\EPORts").
# Capitals only, so "the Bombay High Court Reports" in a footnote is not a head.
_REPORTS = re.compile(r"S\S{0,2}P\S{1,6}\W{0,3}[Cc]\S{2,3}R[Tt]\W{0,3}\S{0,2}EP|Digital Supreme Court Reports")
# "[1985] 1 S.C.R.", OCR'd as "(t9s5j i s.c.il.".
_VOLUME_HEAD = re.compile(r"^[\[(]\s*\S{4}\s*[\])jJ}]\s+(?:SUPP\.?\s*)?\S{1,3}\s+S\s*\.\s*C\s*\.", re.I)
_SCR = re.compile(r"S\s*[.;:,]?\s*C\s*[.;:,]?\s*R\b\.?")
_PAGE_NUMBER = re.compile(r"^[^\w\s]{0,2}\s*\d{1,4}\s*[^\w\s]{0,2}$")
_PRINTER_MARK = re.compile(r"^\d{1,3}\s*[-—]\s*\d{1,3}\s+S\.?\s*C\.?\s+India", re.I)
_TITLE_HEAD = re.compile(r"\s(?:v|vs|V)\.?\s")
# "(Desai, J.)", OCR'd as "(Desai, l.)"; "[DR. ANAND, J.]".
_AUTHOR_IN_HEAD = re.compile(r"[(\[][^)\]]{2,30},\s*\S{1,4}\.?\s*[)\]]")
# A title head set apart from its page number: "RAM RATTAN v. BAJRANG LAL (Desai, J.)      969".
_PAGE_NUMBER_APART = re.compile(r"^\s*\d{2,4}\s{4,}\S|\S\s{4,}\d{2,4}\s*$")

# "(1) [1950] S.C.R. 605." or, in current volumes, "1    (2014) 10 SCC 635". Scans
# often read "(1)" as "(I)" or "(l)".
_FOOTNOTE_START = re.compile(r"^[.·]?\s*(?:\(?\s*[\dIl'!z]{1,2}\s*\)\s*|\d{1,2}\s{2,})\S")
_CITATION_HINT = re.compile(
    r"\b(?:1[89]\d\d|20\d\d)\b|SCC|S\.\s*C\.\s*R|\bAIR\b|U\.\s*S\.|Law\.? Ed|L\.\s*R\.|All ER|A\.C\.|[Ss]upra|reported"
    r"|\sv\.?\s|\bNo\.? ?\d"
)

# The judgment starts after one of these.
_ORDER_OF_COURT = re.compile(r"JUDGMENT\s*/\s*ORDER\s+OF\s+THE\s+SUPREME\s+COURT", re.I)
_DELIVERED = re.compile(
    r"The\s+(?:following\s+)?(?:Judgments?|Orders?|Opinions?)\*?\s+\S{1,3}\s+the\s+Court\s+(?:was|were)\s+"
    r"(?:delivered|passed|pronounced)"
    r"(?:\s+by)?\s*[:.\-]*",
    re.I,
)
_DELIVERED_LOOSE = re.compile(r"\b(?:was|were)\s+delivered\s+by\b", re.I)
_HEADING = re.compile(r"^(?:J\s*U\s*D\s*G\s*M\s*E\s*N\s*T|O\s*R\s*D\s*E\s*R)$", re.I)
# The start of an opinion: "MAHAJAN J.-This", "DESAI, J.-The", "CHANDRACHUD, C. J. The",
# "DR. ANAND, J. This", or "KRISHNA MURARI, J." alone. Capitals only, so a
# sentence citing "Holmes, J." does not match.
_AUTHOR_START = re.compile(
    r"^(?:PER\s+)?(?:DR\.?\s+)?[A-Z][A-Z.'\-:~]+(?:\s+[A-Z][A-Za-z.'\-:~]*){0,6},?\s*"
    r"(?:C\.?\s*J\.?(?:\s*I\.?)?|JJ?\.)\s*(?:[-—–:]|\s[A-Z]|$)"
)

_AUTHOR_ALONE = re.compile(r"^(?:PER\s+)?[A-Z][\w.'\- ]{1,60},\s*(?:C\.?\s*J\.?(?:\s*I\.?)?|JJ?\.)$")

# The judgment ends at the editor's notes.
_TRAILER_LINE = re.compile(r"^(?:Agents?\s+for\b|Headnotes\s+prepared\s+by\b|Result\s+of\s+the\s+case\b)", re.I)
# "Appeal dismissed.", "Appeal allowed in part.", "Directions issued.": printed
# flush right, sometimes after the editor's initials.
_DISPOSAL = re.compile(r"^[A-Z][a-z]+(?:\s+[a-z]+){1,5}\s*\.$")
# After the editor's name or initials, any short sentence: "Divya Pandey
# Matter to be placed before Hon'ble CJI.", "Devika Gujral  Matter referred to larger Bench."
_DISPOSAL_AFTER_EDITOR = re.compile(r"^[A-Z][\w’'.,]*(?:\s+[\w’'.,()]+){1,9}\.$")
_BENCH = re.compile(r"^[\[(].*[A-Z]{3}")


@dataclass
class _Line:
    text: str = ""  # kept text, margins removed
    indent: int = 0  # start of the kept text, relative to the page's text column
    end: int = 0
    width: int = 0  # the page's text column width
    segments: list[tuple[int, int, str]] = field(default_factory=list)  # relative to the column


@dataclass
class ScrText:
    header: str
    body: str
    trailer: str
    footnotes: list[str]
    warnings: list[str]


def _segments(line: str) -> list[tuple[int, int, str]]:
    return [(m.start(), m.end(), m.group()) for m in _GAP.finditer(line)]


def _percentile(values: list[int], q: float) -> int:
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * q))]


def _head_key(raw: str) -> str:
    return re.sub(r"[^a-z]", "", raw.lower())


def _is_running_head(raw: str, repeated: set[str]) -> bool:
    s = " ".join(raw.split())
    if not s:
        return False
    if _REPORTS.search(s) or _VOLUME_HEAD.match(s) or _PAGE_NUMBER.match(s) or _PRINTER_MARK.match(s):
        return True
    if (_SCR.search(s) or re.search(r"REPORTS\b", s)) and len(s) < 45:
        return True
    has_page = bool(re.match(r"^\S{0,2}\d{2,4}\b", s) or re.search(r"\b\d{2,4}\S{0,2}$", s))
    if _TITLE_HEAD.search(s) and (has_page or _AUTHOR_IN_HEAD.search(s) or _head_key(s) in repeated):
        return True
    return False


def _is_wrapped_title_head(first: str, second: str) -> bool:
    """A title head wrapped over two lines, with the page number on the first
    and " v. " only on the second: "SUPREME COURT ADVOCATES-ON-RECORD    979" /
    "ASSOCIATION v. UNION OF INDIA"."""
    a, b = " ".join(first.split()), " ".join(second.split())
    has_page = re.search(r"\s\d{2,4}$", a) or re.match(r"^\d{2,4}\s", a)
    caps = not re.search(r"[a-z]", a) and not re.search(r"[a-z]", _TITLE_HEAD.sub(" ", b))
    return bool(has_page and caps and _TITLE_HEAD.search(b))


def _strip_page_furniture(lines: list[str], repeated: set[str]) -> tuple[list[str], list[str]]:
    """Drop running heads and page numbers. Returns (kept lines, footnote lines).

    `repeated` holds title lines found at the top of more than one page: the
    current volumes print the title head with no page number beside it.
    """
    content = [i for i, ln in enumerate(lines) if ln.strip()]
    drop: set[int] = set()
    # Running heads: up to four lines at the top of the page.
    prev_head = False
    for n, i in enumerate(content[:4]):
        if _is_running_head(lines[i], repeated) or (
            n == 0 and len(content) > 1 and _is_wrapped_title_head(lines[i], lines[content[1]])
        ):
            drop.add(i)
            prev_head = True
            continue
        # The second line of a wrapped title head ("PEOPLE'S UNION ... OF 371" / "MAHARASHTRA").
        s = lines[i].strip()
        if prev_head and n < 3 and s.isupper() and len(s) < 40 and _TITLE_HEAD.search(lines[content[n - 1]]):
            drop.add(i)
            continue
        if n == 0 and len(s) <= 3:
            drop.add(i)  # OCR debris above the head on scanned pages
            continue
        break
    # Page numbers and printer's marks at the foot.
    for i in reversed(content[-3:]):
        s = lines[i].strip()
        if _PAGE_NUMBER.match(s) or _PRINTER_MARK.match(s) or _VOLUME_HEAD.match(s) or len(s) <= 2:
            drop.add(i)
        else:
            break
    kept = [ln if i not in drop else "" for i, ln in enumerate(lines)]

    # Footnotes: a short block at the foot that starts with a note number and cites something.
    content = [i for i, ln in enumerate(kept) if ln.strip()]
    footnotes: list[str] = []
    for start in content[-6:]:
        block = [re.sub(r"^[A-H]\s{2,}", "", kept[i].strip()) for i in content if i >= start]
        if _FOOTNOTE_START.match(block[0]) and _CITATION_HINT.search(" ".join(block)):
            for line in block:
                if _FOOTNOTE_START.match(line) or not footnotes:
                    footnotes.append(line)
                else:
                    footnotes[-1] += " " + line
            footnotes = [re.sub(r"\s+[A-H]$", "", " ".join(f.split())) for f in footnotes]
            kept = kept[:start]
            break
    return kept, footnotes


def _page_lines(lines: list[str], lettered: bool) -> list[_Line]:
    """Remove margins from a page's lines. `lettered` says the volume prints
    A-H margin letters, so a capital letter one space from the text can be
    taken for one."""
    segs = [_segments(ln) for ln in lines]
    long = [s for line in segs for s in line if s[1] - s[0] >= 25]
    if len(long) >= 5:
        left = _percentile([s[0] for s in long], 0.1)
        right = _percentile([s[1] for s in long], 0.9)
    else:
        left, right = 0, max((len(ln) for ln in lines), default=0)

    out: list[_Line] = []
    for line_segs in segs:
        line = _Line(width=right - left)
        keep: list[tuple[int, int, str]] = []
        for k, (start, end, text) in enumerate(line_segs):
            first_or_last = k == 0 or k == len(line_segs) - 1
            margin_letter = _MARGIN_LETTER.match(text) or (lettered and _MARGIN_LETTER_OCR.match(text))
            if margin_letter and first_or_last:
                continue
            if end <= left - 2:
                # Left of the column: a marginal note, unless it is a hanging
                # paragraph number in front of text.
                if not (_HANGING_NUMBER.match(text) and k + 1 < len(line_segs)):
                    continue
            elif start >= right + 2 and (keep or start - left > 0.75 * (right - left)):
                continue  # right margin
            keep.append((start, end, text))
        if keep:
            # A margin letter only one space from the text: "D considering ...", "... informed A".
            start, end, text = keep[0]
            if (
                (m := _LEADING_DEBRIS.match(text))
                or (lettered and (m := _LEADING_LETTER_ANYWHERE.match(text)))
                or (lettered and start < left - 1 and (m := _LEADING_LETTER.match(text)))
            ):
                keep[0] = (start + m.end(), end, text[m.end() :])
            start, end, text = keep[-1]
            if (
                lettered
                and (
                    end > right + 1
                    or re.search(r"[a-z,;.\-] [B-H]$", text)
                    or (end >= right - 3 and re.search(r"[a-z,;.\-] A$", text))
                )
                and (m := _TRAILING_LETTER.search(text))
            ):
                keep[-1] = (start, end - len(m.group()), text[: m.start()])
            keep = [k for k in keep if k[2]]
        if keep:
            line.segments = [(start - left, end - left, text) for start, end, text in keep]
            line.text = " ".join(" ".join(t for _, _, t in keep).split())
            if lettered:
                line.text = _INLINE_LETTER.sub("", line.text)
            line.indent = keep[0][0] - left
            line.end = keep[-1][1] - left
        out.append(line)
    return out


def _with_paragraph_breaks(lines: list[_Line]) -> list[str]:
    """Join lines into text, putting a blank line before each paragraph.

    A paragraph starts where a line is indented further than the one before
    and the one before ended a sentence or fell short of the column; where an
    indented first line follows the end of a block quote; or where a
    paragraph number hangs left of the column. Lines with no letters or
    digits are scan debris and are dropped.
    """
    out: list[str] = []
    prev: _Line | None = None
    for ln in lines:
        if not re.search(r"\w", ln.text):
            continue
        if prev is not None:
            indented = ln.indent >= prev.indent + 2 and ln.indent >= 2
            prev_done = prev.text[-1] in ".:;?!\"'”’-—)" or prev.end < prev.width - 10
            hanging = ln.indent <= prev.indent - 2 and bool(_HANGING_NUMBER.match(ln.segments[0][2]))
            ended = prev.text[-1] in ".:;?!\"'”’)"
            closed_quote = prev.text[-1] in "\"'”’" and prev.end < prev.width - 8
            after_quote = ln.indent >= 2 and ended and (ln.indent <= prev.indent - 2 or closed_quote)
            centred = ln.indent > ln.width * 0.25 and len(ln.text) < ln.width * 0.5
            # A judge's name on its own line starts an opinion ("Ujjal Bhuyan, J.").
            author = bool(_AUTHOR_ALONE.match(ln.text)) and prev.text[-1] in '.:"”)'
            if (
                (indented and prev_done)
                or hanging
                or after_quote
                or centred
                or author
                or (prev.indent > prev.width * 0.25 and prev_done)
            ):
                out.append("")
        out.append(ln.text)
        prev = ln
    return out


def _is_disposal(ln: _Line) -> bool:
    if not ln.segments:
        return False
    start, _, text = ln.segments[-1]
    if start <= ln.width * 0.35 or len(ln.segments) > 2:
        return False
    if len(ln.segments) == 2 and len(ln.segments[0][2]) <= 30:
        return bool(_DISPOSAL_AFTER_EDITOR.match(text))
    return bool(_DISPOSAL.match(text))


_LIGATURES = str.maketrans({"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl"})
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0e-\x1f\x7f]")


def _pages(text: str) -> list[str]:
    """Split at form feeds, and also where a running head turns up mid-page:
    scanned volumes are sometimes cut so that one PDF page holds the foot of
    one printed page and the head of the next."""
    text = _CONTROL.sub("", text.replace("\r\n", "\n").translate(_LIGATURES))
    pages: list[str] = []
    for page in text.split("\f"):
        lines = page.split("\n")
        content = [i for i, ln in enumerate(lines) if ln.strip()]
        cuts = [
            i
            for i in content[1:]
            if _REPORTS.search(lines[i])
            or (_TITLE_HEAD.search(lines[i]) and _PAGE_NUMBER_APART.search(lines[i]) and len(lines[i].split()) < 14)
        ]
        start = 0
        for cut in cuts:
            pages.append("\n".join(lines[start:cut]))
            start = cut
        pages.append("\n".join(lines[start:]))
    return pages


def clean_scr(text: str) -> ScrText:
    lines: list[_Line] = []
    footnotes: list[str] = []
    warnings: list[str] = []
    pages = [[ln.expandtabs().rstrip() for ln in page.split("\n")] for page in _pages(text)]
    tops = [[ln for ln in page if ln.strip()][:4] for page in pages]
    keys = [_head_key(ln) for top in tops for ln in top if _TITLE_HEAD.search(ln)]
    repeated = {k for k in keys if keys.count(k) > 1}
    letter_lines = sum(
        1 for page in pages for ln in page if any(_MARGIN_LETTER_STRICT.match(seg) for _, _, seg in _segments(ln))
    )
    lettered = letter_lines >= 5
    for page in pages:
        kept, notes = _strip_page_furniture(page, repeated)
        footnotes += notes
        lines += _page_lines(kept, lettered)
    lines = [ln for ln in lines if ln.text]

    # On scanned volumes the first page can open with the end of the previous
    # case: drop everything up to its disposal and agents, before our bench line.
    benches = [i for i, ln in enumerate(lines[:80]) if _BENCH.match(ln.text)]
    bench = next((i for i in benches if re.search(r"J\.?\]", lines[i].text)), benches[0] if benches else None)
    if bench is not None:
        ends = [i for i in range(bench) if _TRAILER_LINE.match(lines[i].text) or _is_disposal(lines[i])]
        if ends:
            lines = lines[ends[-1] + 1 :]

    header_end, body_start, opening = _judgment_start(lines)
    if body_start is None:
        warnings.append("Could not find where the judgment starts; treated the whole text as the judgment.")
        header_end = body_start = 0

    body_end = next(
        (i for i in range(body_start, len(lines)) if _TRAILER_LINE.match(lines[i].text) or _is_disposal(lines[i])),
        None,
    )
    if body_end is None:
        warnings.append("Could not find the end of the judgment (no disposal line or agents).")
        body_end = len(lines)

    header = "\n".join([ln.text for ln in lines[:header_end]] + opening[:1])
    body = "\n".join(opening[1:] + _with_paragraph_breaks(lines[body_start:body_end]))
    return ScrText(
        header=header.strip(),
        body=body.strip() + "\n",
        trailer="\n".join(ln.text for ln in lines[body_end:]),
        footnotes=footnotes,
        warnings=warnings,
    )


def _judgment_start(lines: list[_Line]) -> tuple[int, int | None, list[str]]:
    """Where the header ends and the body starts, and any text from the line
    that holds the start marker: [text before it, marker, blank, any text after].

    The body starts after "JUDGMENT / ORDER OF THE SUPREME COURT" (current
    volumes), at the author line after "The Judgment of the Court was
    delivered by", or at a JUDGMENT/ORDER heading. An order of the Court with
    no author keeps its "The following Order of the Court was delivered"
    line, so the splitter knows an opinion starts there.
    """
    for i, ln in enumerate(lines):
        if _ORDER_OF_COURT.search(ln.text):
            return i + 1, i + 1, []
    joined, offsets = _join(lines)
    if m := (_DELIVERED.search(joined) or _DELIVERED_LOOSE.search(joined)):
        first, last = _line_at(offsets, m.start()), _line_at(offsets, m.end() - 1)
        for j in range(last, min(last + 6, len(lines))):
            if _AUTHOR_START.match(lines[j].text):
                return j, j, []
        if m.re is _DELIVERED:
            before = joined[offsets[first] : m.start()].strip()
            after = joined[m.end() : offsets[last] + len(lines[last].text)].strip()
            return first, last + 1, [before, " ".join(m.group().split()), ""] + ([after] if after else [])
    for i, ln in enumerate(lines):
        if _HEADING.match(ln.text):
            return i, i, []
    return 0, None, []


def _join(lines: list[_Line]) -> tuple[str, list[int]]:
    offsets, parts, pos = [], [], 0
    for ln in lines:
        offsets.append(pos)
        parts.append(ln.text)
        pos += len(ln.text) + 1
    return "\n".join(parts), offsets


def _line_at(offsets: list[int], pos: int) -> int:
    lo = 0
    for i, off in enumerate(offsets):
        if off <= pos:
            lo = i
        else:
            break
    return lo
