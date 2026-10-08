"""Clean the text of a judgment PDF from the Supreme Court's website before it
is split.

The website (www.sci.gov.in, PDFs served from api.sci.gov.in) has two kinds of
judgment PDF, and both differ from Digital SCR reports (see `scr.py`):

* JUDIS text (judgments up to about 2009): plain text set in PDF pages, each
  headed "http://JUDIS.NIC.IN  SUPREME COURT OF INDIA  Page 3 of 22". Up to
  about 2000 the text is the SCR report's: a metadata block (PETITIONER,
  BENCH, CITATION, HEADNOTE), then "JUDGMENT:", the reporter's preamble and
  the judgment, with the SCR page numbers and footnotes left where the
  printed pages broke. Lines are flush left, so a paragraph ends where a line
  falls short. Texts from the 1980s were cut to a fixed width: the end of
  each long line ("ha" of "have") is printed at the start of the next one.
* The signed judgment itself (about 2010 onwards): the cause title,
  "J U D G M E N T" or "ORDER", the author, numbered paragraphs, signature
  blocks, "New Delhi;" and the date. Pages carry "Page 3 of 22", page
  numbers and a running line with the case number; recent judgments carry the
  "Signature Not Verified" stamp in the margin of the first page, beside the
  text. Lines are often double-spaced, so blank lines do not mark
  paragraphs. Long judgments open with a table of contents, a separate
  opinion may come with its own cover page, and the court master's Record of
  Proceedings is sometimes appended.

`clean_sci` returns the same parts as `scr.clean_scr`: the header (cause
title, metadata, headnotes, counsel), the judgment body for the splitter, the
trailer (editor's initials and disposal, Record of Proceedings) and the
footnotes. Tuned on the samples in tests/fixtures/sci.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from app.judgments import _is_caps_heading
from app.scr import (
    _AUTHOR_START,
    _CITATION_HINT,
    _GAP,
    _TRAILER_LINE,
    ScrText,
    _judgment_start,
    _Line,
    _percentile,
)

_LIGATURES = str.maketrans({"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl"})
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0e-\x1f\x7f]")
# JUDIS texts from the 2000s print dashes as the escapes "\027" and "\026".
_ESCAPES = {"\\027": "—", "\\026": "–"}

_JUDIS_HEAD = re.compile(r"^\s*http://JUDIS\.NIC\.IN\b", re.I)
_LONE_NUMBER = re.compile(r"^\s*\d{1,4}\s*$")
_JUDIS_MARKER = re.compile(r"^\s*JUDGMENT:\s*$")
# "(1) [1957] 31 I.T.R. 826." at the foot of a printed page.
_JUDIS_NOTE = re.compile(r"^\(\s*\d{1,2}\s*\)\s*\S")
# The editor's initials at the end of a report: "T.N.A.", "V. P. S.".
_INITIALS = re.compile(r"^(?:[A-Z]\.\s?){2,4}$")
# "Appeal dismissed.", "Writ issued," printed to the right.
_DISPOSAL = re.compile(r"^[A-Z][a-z]+(?:\s+[a-z]+){1,5}\s*[.,]?$")

# Page furniture of the signed judgments.
_PAGE_OF = re.compile(r"\bPage\s+\d+(?:\s+of\s+\d+)?\s*$", re.I)
_PAGE_NUMBER = re.compile(r"^\s*[-–]?\s*\d{1,4}\s*[-–]?\s*$")
_STAMP_START = "Signature Not Verified"
_STAMP_DATE = re.compile(r"^Date:\s*\d{4}[.\-]\d{2}[.\-]\d{2}")
_STAMP_TIME = re.compile(r"^\d{1,2}:\d{2}:\d{2}(?:\s*[A-Z]{2,4})?$")
_FOOTNOTE = re.compile(r"^\s*(?P<num>\d{1,3})(?:\s+(?P<text>\S.*))?$")
# A table of contents: "(A). FACTUAL MATRIX ........ 6", "BRIEF FACTS ...... 3".
_LEADER = re.compile(r"(?:\.{4,}|…{2,}|(?:\.\s){4,})\s*\.*\s*\d{0,4}\s*$")
_CONTENTS_HEADING = re.compile(r"^(?:INDEX|CONTENTS|TABLE OF CONTENTS)$", re.I)
_HEADING = re.compile(r"^(?:J\s*U\s*D\s*G\s*M\s*E\s*N\s*T|O\s*R\s*D\s*E\s*R)$", re.I)
_COURT_TITLE = re.compile(r"^IN\s+THE\s+SUPREME\s+COURT\s+OF\s+INDIA$", re.I)
_PROCEEDINGS = re.compile(r"^RECORD\s+OF\s+PROCEEDINGS$", re.I)
_ITEM = re.compile(r"^ITEM\s+NO\b", re.I)
# Lines the splitter must see on their own: author lines, signatures, the
# bracketed name under a signature, place and date.
_STANDALONE = re.compile(
    r"^(?:(?:Dr\.?\s*)?[A-Z][A-Za-z.' \-]{1,40},\s*(?:C\.?\s*J\.?(?:\s*I\.?)?|JJ?\.?)\s*[:.\-—–]*"
    r"|[.…·\s]{3,}\s*J\.?"
    r"|[\[(]\s*[A-Z][A-Za-z.\s'\-]+[\])]"
    r"|New\s+Delhi[;,.]?"
    r"|(?:\d{1,2}(?:st|nd|rd|th)?\s+)?(?:January|February|March|April|May|June|July|August|September|October"
    r"|November|December),?\s+(?:\d{1,2},?\s+)?\d{4}\.?)$",
    re.I,
)
# A line that ends in an initial or a title has not finished its sentence:
# "... operated by Dr. P." / "Jagannath on 25.10.2002".
_ABBREVIATION_END = re.compile(r"(?:\b[A-Z]|\b(?:Dr|Mr|Mrs|Ms|Messrs|No|Nos|Sh|Smt|Shri|St|vs?|viz|i\.e|e\.g))\.$")
_NUMBERED = re.compile(r"^\d{1,3}(?:\.\d{1,3})*\.\s")


def _normalise(text: str) -> str:
    text = text.replace("\r\n", "\n").translate(_LIGATURES)
    for esc, dash in _ESCAPES.items():
        text = text.replace(esc, dash)
    return _CONTROL.sub("", text)  # keeps "\f", the page break


def clean_sci(text: str) -> ScrText:
    text = _normalise(text)
    head = text.lstrip()[:200]
    if _JUDIS_HEAD.match(head):
        return _clean_judis(text)
    return _clean_signed(text)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _words(lines: list[str]) -> Counter[str]:
    words: Counter[str] = Counter()
    for line in lines:
        words.update(w.lower() for w in re.findall(r"[A-Za-z]+", line))
    return words


# JUDIS text


@dataclass
class _Row:
    text: str  # as extracted, with its indentation
    cont: bool = False  # the sentence runs on past a page break


# Words that end a cut line far more often than they finish a cut word.
_SHORT_WORDS = frozenset(
    "a an and any are as at be but by can do for had has he her his if in is it its may no not now of on or "
    "our she so the to up was we who".split()
)


def _merge_tails(lines: list[str]) -> list[str]:
    """Put back the ends of lines that were cut at a fixed width and printed at
    the start of the next line ("... has been heard" / "on"). Whether the cut
    fell inside a word is decided by the judgment's own words: "ha" + "ve" is
    "have", "heard" + "on" stays two words."""
    long = [_indent(ln) for ln in lines if len(ln.strip()) > 40]
    if not long or Counter(long).most_common(1)[0][0] < 4:
        return lines
    words = _words(lines)
    out: list[str] = []
    for line in lines:
        s = line.strip()
        prev = out[-1] if out else ""
        if s and _indent(line) <= 1 and len(s) <= 12 and len(s.split()) <= 2 and _indent(prev) >= 4 and prev.strip():
            a = prev.split()[-1]
            b = s.split()[0]
            head = re.sub(r"\W+$", "", a)
            tail = re.sub(r"^\W+|\W+$", "", b)
            if head != a or not head or not tail:
                joined = False  # "Ms." / "S.": the cut fell after punctuation
            elif head.isdigit() and (tail.isdigit() or tail in ("st", "nd", "rd", "th")):
                joined = True  # "19" / "89", "7" / "th"
            elif words[(head + tail).lower()] > 0:
                joined = True  # "ha" / "ve": "have" is in the judgment
            elif head.isdigit() != tail.isdigit() or tail.lower() in _SHORT_WORDS:
                joined = False  # "30" / "to", "heard" / "on"
            else:
                joined = not (words[head.lower()] > 1 and words[tail.lower()] > 1)
            out[-1] = prev + ("" if joined else " ") + s
            continue
        out.append(line)
    return out


def _is_judis_note(line: str) -> bool:
    """A footnote above an SCR page number: "(5) 68 L.E.D. 999. (6) 86 L. E.d. 1302."."""
    s = line.strip()
    m = _JUDIS_NOTE.match(s)
    return bool(m) and bool(_CITATION_HINT.search(s) or re.search(r"\d", s[m.end() - 1 :]))


def _clean_judis(text: str) -> ScrText:
    # Blank lines at the top and foot of a PDF page are not paragraph breaks.
    lines = []
    for page in text.split("\f"):
        page_lines = [ln.expandtabs().rstrip() for ln in page.split("\n") if not _JUDIS_HEAD.match(ln)]
        content = [i for i, ln in enumerate(page_lines) if ln.strip()]
        if content:
            lines += page_lines[content[0] : content[-1] + 1]
    lines = _merge_tails(lines)

    # SCR page numbers sit on lines of their own, with the printed page's
    # footnotes just above them.
    rows: list[_Row] = []
    footnotes: list[str] = []
    for line in lines:
        if _LONE_NUMBER.match(line):
            notes: list[str] = []
            while rows and _is_judis_note(rows[-1].text):
                note_line = " ".join(rows.pop().text.split())
                notes[:0] = re.split(r"\s+(?=\(\s*\d{1,2}\s*\)\s)", note_line)  # "(1) ... (2) ..."
            footnotes += notes
            if rows:
                rows[-1].cont = True
            continue
        rows.append(_Row(line))

    marker = next((i for i, r in enumerate(rows) if _JUDIS_MARKER.match(r.text)), None)
    header = [r.text.strip() for r in rows[: marker or 0]]
    rows = rows[marker + 1 :] if marker is not None else rows
    rows = _capitalise_announced_authors(rows)

    # The editor's notes at the end: initials, agents, and the disposal,
    # printed to the right or next to the other notes.
    content = [i for i, r in enumerate(rows) if r.text.strip()]
    width = _percentile([len(rows[i].text) for i in content], 0.9) if content else 0
    trailer_start, notes_seen = len(rows), False
    for i in reversed(content[-6:]):
        s = rows[i].text.strip()
        note = bool(_INITIALS.match(s) or _TRAILER_LINE.match(s))
        disposal = bool(_DISPOSAL.match(s))
        if not (note or (disposal and (notes_seen or _indent(rows[i].text) > width * 0.3))):
            if disposal and not notes_seen:
                continue  # "Petition dismissed" before "V. P. S." is checked with it
            break
        trailer_start, notes_seen = i, notes_seen or note or _indent(rows[i].text) > width * 0.3
    trailer = [r.text.strip() for r in rows[trailer_start:] if r.text.strip()]
    rows = rows[:trailer_start]

    lines_ = [_Line(text=" ".join(r.text.split())) for r in rows]
    header_end, body_start, opening = _judgment_start(lines_)
    if body_start is None:
        # "The following judgments were delivered:--" names nobody: the body
        # starts at the first author line, after the reporter's preamble.
        first = next((i for i, ln in enumerate(lines_[:60]) if _AUTHOR_START.match(ln.text)), 0)
        header_end = body_start = first
    header += [ln.text for ln in lines_[:header_end] if ln.text] + opening[:1]
    body = opening[1:] + _judis_paragraphs(rows[body_start:], width)
    return ScrText(
        header="\n".join(h for h in header if h).strip(),
        body="\n".join(body).strip() + "\n",
        trailer="\n".join(trailer),
        footnotes=footnotes,
        warnings=[],
    )


_ANNOUNCED = re.compile(r"(?:was|were)\s+delivered\s+by|delivered\s+(?:a\s+)?(?:separate|seperate|dissenting)", re.I)
_TITLE_CASE_AUTHOR = re.compile(
    r"^(?P<name>[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}),\s*(?P<title>C\.\s*J\.|J\.)\s+(?=[A-Z])"
)


def _capitalise_announced_authors(rows: list[_Row]) -> list[_Row]:
    """JUDIS prints some authors in title case with no dash ("Subba Rao, C.J.
    This petition ..."), which the splitter cannot tell from a sentence that
    starts with a judge's name. Where the reporter's preamble names the judge
    as delivering a judgment ("... was delivered by SUBBA RAO, C.J. BACHAWAT,
    J. delivered a separate ..."), print the name in capitals as SCR does."""
    preamble = " ".join(r.text for r in rows[:40])
    if not _ANNOUNCED.search(preamble):
        return rows
    for r in rows:
        stripped = r.text.lstrip()
        m = _TITLE_CASE_AUTHOR.match(stripped)
        if m and re.search(rf"\b{re.escape(m['name'].upper())},", preamble):
            r.text = r.text[: _indent(r.text)] + m["name"].upper() + stripped[len(m["name"]) :]
    return rows


def _judis_paragraphs(rows: list[_Row], width: int) -> list[str]:
    """Join JUDIS lines into text with a blank line between paragraphs. A
    paragraph ends where a line ends a sentence well short of the column (and
    does not run on past a page break), or where the next line is indented
    further or less, as quotations are."""
    out: list[str] = []
    prev: _Row | None = None
    quoting = False  # the previous two lines were indented alike: a block quotation
    blank = False
    for r in rows:
        s = r.text.strip()
        if not s:
            blank = True
            continue
        if prev is not None:
            p = prev.text.strip()
            ended = _ends_sentence(p) and not p.endswith(";")  # the clauses of a quoted rule
            short = len(prev.text) < width * 0.8 and not prev.cont
            indent, prev_indent = _indent(r.text), _indent(prev.text)
            quote_ended = ended or (quoting and p[-1] in "\"”’'")  # '... xx xx"'
            if (
                blank
                or (short and ended)
                or (indent >= prev_indent + 2 and (ended or short))
                or (indent <= prev_indent - 2 and quote_ended)
                or (ended and _AUTHOR_START.match(s))  # "FAZL ALI J.--I agree." after a full line
            ):
                out.append("")
            quoting = abs(indent - prev_indent) <= 1 and indent >= 4
        out.append(" ".join(s.split()))
        prev = r
        blank = False
    return out


# Signed judgments


@dataclass
class _PageLine:
    text: str  # without margins, single-spaced
    indent: int  # relative to the page's text column
    blanks: int  # blank lines before it on the page
    page_start: bool
    end: int = 0  # where the line ends, relative to the text column
    width: int = 0  # the page's text column width
    spacing: int = 0  # the usual number of blank lines between lines on its page


def _strip_stamp(lines: list[str]) -> list[str]:
    """Remove the "Signature Not Verified" stamp, which shares lines with the
    text: "Signature Not Verified    Odisha, when it was detained ..."."""
    out = []
    state = 0  # 1: after "Signature Not Verified", 2: signer's name, 3: date and time
    for line in lines:
        segs = list(_GAP.finditer(line))
        first = segs[0].group() if segs else ""
        drop = False
        if first == _STAMP_START:
            state, drop = 1, True
        elif state == 1 and first.startswith("Digitally signed"):
            state, drop = 2, True
        elif state == 2 and _STAMP_DATE.match(first):
            state, drop = 3, True
        elif state == 2 and first and first.upper() == first:
            drop = True  # the signer's name, on one or two lines
        elif state == 3 and _STAMP_TIME.match(first):
            drop = True
        elif state == 3 and first.startswith("Reason:"):
            state, drop = 0, True
        elif state and first:
            state = 0
        if drop:
            line = " " * segs[0].end() + line[segs[0].end() :]
        if (drop or state) and not line.strip():
            continue  # the stamp's own lines are not blank lines in the text
        out.append(line)
    return out


def _running_lines(pages: list[list[str]]) -> set[str]:
    """Lines printed at the top or foot of several pages: the case number."""
    keys: Counter[str] = Counter()
    for lines in pages:
        content = [ln for ln in lines if ln.strip()]
        keys.update({" ".join(ln.split()) for ln in content[:2] + content[-3:]})
    return {k for k, n in keys.items() if n >= 3 and n >= len(pages) * 0.3}


def _strip_furniture(lines: list[str], running: set[str]) -> list[str]:
    content = [i for i, ln in enumerate(lines) if ln.strip()]
    drop = set()
    for edge in (content[:3], list(reversed(content[-4:]))):
        for i in edge:
            s = " ".join(lines[i].split())
            if _PAGE_NUMBER.match(s) or _PAGE_OF.search(s) or s in running:
                drop.add(i)
            else:
                break
    return ["" if i in drop else ln for i, ln in enumerate(lines)]


def _take_footnotes(lines: list[str], expected: int) -> tuple[list[str], list[str]]:
    """Footnotes at the foot of a page: the next note number the judgment is
    due ("1", then "2", across pages) at the start of a line, with the rest of
    the page below it. A number alone on its line counts only when the note's
    text follows."""
    content = [i for i, ln in enumerate(lines) if ln.strip()]
    for n, i in enumerate(content[-25:]):
        m = _FOOTNOTE.match(lines[i])
        if not m or int(m["num"]) != expected:
            continue
        rest = content[-25:][n + 1 :]
        if not m["text"] and not rest:
            continue
        notes: list[str] = []
        due = expected
        for j in [i] + rest:
            fm = _FOOTNOTE.match(lines[j])
            if fm and int(fm["num"]) == due and (fm["text"] or j != content[-1]):
                notes.append(fm["num"] + (" " + fm["text"].strip() if fm["text"] else ""))
                due += 1
            else:
                notes[-1] += " " + lines[j].strip()
        return lines[:i], [" ".join(n.split()) for n in notes]
    return lines, []


def _drop_contents(lines: list[_PageLine]) -> list[_PageLine]:
    """Drop tables of contents: three or more lines ending in dot leaders and
    a page number, no more than six lines apart (an entry can wrap), with the
    "INDEX" heading above them."""
    leaders = [i for i, ln in enumerate(lines) if _LEADER.search(ln.text)]
    drop: set[int] = set()
    run = leaders[:1]
    for i in leaders[1:] + [None]:
        if i is not None and i - run[-1] <= 6:
            run.append(i)
            continue
        if len(run) >= 3:
            start = run[0] - 1 if run[0] > 0 and _CONTENTS_HEADING.match(lines[run[0] - 1].text) else run[0]
            drop.update(range(start, run[-1] + 1))
        run = [i]
    return [ln for i, ln in enumerate(lines) if i not in drop]


def _page_lines(lines: list[str]) -> list[_PageLine]:
    segs = [list(_GAP.finditer(ln)) for ln in lines]
    long = [s for s in segs if s and len(" ".join(m.group() for m in s)) >= 30]
    left = _percentile([s[0].start() for s in long], 0.1) if len(long) >= 3 else 0
    right = _percentile([s[-1].end() for s in long], 0.9) if len(long) >= 3 else max(map(len, lines), default=0)
    out: list[_PageLine] = []
    blanks = 0
    for ss in segs:
        if not ss:
            blanks += 1
            continue
        text = " ".join(" ".join(m.group() for m in ss).split())
        out.append(_PageLine(text, ss[0].start() - left, blanks, not out, end=ss[-1].end() - left, width=right - left))
        blanks = 0
    return out


def _set_spacing(lines: list[_PageLine], pages: list[int]) -> None:
    """Record the usual gap between lines of a paragraph, measured after lines
    that stop mid-sentence. Cover pages and appended orders are single-spaced
    and the judgment often double-spaced, so it is judged page by page, with
    the whole judgment's as the fallback."""

    def gaps(idx: list[int]) -> Counter[int]:
        return Counter(
            lines[i].blanks
            for i in idx
            if i > 0 and not lines[i].page_start and lines[i - 1].text[-1] not in ".:;?!\"'”’)]"
        )

    overall = gaps(list(range(len(lines))))
    fallback = overall.most_common(1)[0][0] if overall else 0
    for page in sorted(set(pages)):
        idx = [i for i, p in enumerate(pages) if p == page]
        counts = gaps(idx)
        spacing = counts.most_common(1)[0][0] if sum(counts.values()) >= 4 else fallback
        for i in idx:
            lines[i].spacing = spacing


def _ends_sentence(text: str) -> bool:
    """Whether a line ends a sentence. A closing quote or bracket counts only
    after a full stop ('... in force.”'), or round a whole line ("(Emphasis
    supplied)"): "Cruzan (supra)" and "‘act’" end in the middle of one."""
    if _ABBREVIATION_END.search(text):
        return False
    if text[-1] in ".:;?!":
        return True
    if text[-1] in "\"'”’)]":
        return len(text) > 1 and (text[-2] in ".:;?!" or (text[0] in "([" and text[-1] in ")]"))
    return False


def _signed_paragraphs(lines: list[_PageLine]) -> list[str]:
    """Join lines into text with a blank line between paragraphs. Many
    judgments are double-spaced, so a paragraph break is a wider gap than the
    usual one between lines, a paragraph number at the start of a line, or a
    change of indentation after a finished sentence."""
    out: list[str] = []
    prev: _PageLine | None = None
    for ln in lines:
        if prev is not None:
            ended = _ends_sentence(prev.text)
            # A blank line ends a paragraph only after a finished sentence:
            # one that stops short of the margin, or a wider gap than usual.
            short = prev.end < prev.width - 8
            wide = ln.blanks > ln.spacing
            gap = not ln.page_start and ln.blanks > 0 and ((ended and short) or (wide and (ended or short)))
            numbered = bool(_NUMBERED.match(ln.text)) and (ended or short or ln.indent <= prev.indent - 2)
            indented = ln.indent >= prev.indent + 3 and ended
            outdented = ln.indent <= prev.indent - 3 and ended
            alone = bool(_STANDALONE.match(ln.text) or _STANDALONE.match(prev.text))
            # A heading in capitals may wrap over several lines; capitals in
            # the middle of a sentence are not a heading.
            caps, prev_caps = _is_caps_heading(ln.text), _is_caps_heading(prev.text)
            heading = any(_HEADING.match(t) for t in (ln.text, prev.text)) or (
                (caps and not prev_caps and (ended or (short and wide)))
                or (prev_caps and not caps and prev.text[-1] not in ",-" and (ended or prev.end < prev.width * 0.75))
            )
            if caps and prev_caps:
                gap = False  # a heading wrapped over two lines, with space between
            if gap or numbered or indented or outdented or alone or heading:
                out.append("")
        out.append(ln.text)
        prev = ln
    return out


def _clean_signed(text: str) -> ScrText:
    pages = [[ln.expandtabs().rstrip() for ln in page.split("\n")] for page in text.split("\f")]
    pages = [p for p in pages if any(ln.strip() for ln in p)]
    running = _running_lines(pages)
    footnotes: list[str] = []
    lines: list[_PageLine] = []
    page_of: list[int] = []
    due, restart = 1, False
    for n, page in enumerate(pages):
        page = _strip_furniture(_strip_stamp(page), running)
        # A separate opinion numbers its footnotes from 1 again.
        restart = restart or bool(footnotes and any(_HEADING.match(ln.strip()) for ln in page))
        page, notes = _take_footnotes(page, due)
        if not notes and restart:
            page, notes = _take_footnotes(page, 1)
        if notes:
            restart = False
            due = int(notes[-1].split()[0]) + 1
        footnotes += notes
        new = _page_lines(page)
        lines += new
        page_of += [n] * len(new)
    _set_spacing(lines, page_of)
    lines = _drop_contents(lines)
    texts = _signed_paragraphs(lines)

    warnings: list[str] = []
    start = next((i for i, t in enumerate(texts) if _HEADING.match(t)), None)
    if start is None:
        warnings.append("Could not find where the judgment starts; treated the whole text as the judgment.")
        start = 0
    end = len(texts)
    for i in range(start, len(texts)):
        if _PROCEEDINGS.match(texts[i]):
            items = [j for j in range(max(start, i - 6), i) if _ITEM.match(texts[j])]
            end = items[0] if items else i
            break
    body = _drop_cover_pages(texts[start:end])
    return ScrText(
        header="\n".join(t for t in texts[:start] if t).strip(),
        body="\n".join(body).strip() + "\n",
        trailer="\n".join(t for t in texts[end:] if t),
        footnotes=footnotes,
        warnings=warnings,
    )


def _drop_cover_pages(texts: list[str]) -> list[str]:
    """A separate opinion can start on a fresh cover page that repeats the
    cause title. Drop it: everything between the previous opinion's place and
    date (or signatures) and the next JUDGMENT heading, when it holds "IN THE
    SUPREME COURT OF INDIA"."""
    out = list(texts)
    headings = [i for i, t in enumerate(out) if _HEADING.match(t)]
    for k in reversed(headings[1:]):
        end = next((i for i in range(k - 1, -1, -1) if _STANDALONE.match(out[i])), None)
        if end is not None and any(_COURT_TITLE.match(out[i]) for i in range(end, k)):
            del out[end + 1 : k]
    return out
