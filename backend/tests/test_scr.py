"""The cleaner and splitter on real judgments: Digital SCR PDFs from 1950 to
2024, extracted with `pdftotext -layout` (tests/fixtures/scr, sources.yaml).

The expected values were checked by reading each judgment's output against
the PDF. When a change to the cleaner or splitter moves one, read that
judgment again before updating it.
"""

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import pytest
import yaml

from app.judgments import SplitJudgment, split_judgment
from app.scr import ScrText, clean_scr

FIXTURES = Path(__file__).parent / "fixtures" / "scr"


@dataclass
class Expected:
    authors: list[list[str]]
    paragraphs: int
    numbers: list[str]
    footnotes: int
    first: str  # start of the first paragraph
    last: str  # end of the last paragraph
    trailer: str  # first line after the judgment


EXPECTED = {
    # Scanned. Majority by Patanjali Sastri J., dissent by Fazl Ali J. (OCR'd "FAZL Au").
    "1950_1_594_605": Expected(
        authors=[["PATANJALI SASTRI"], ["FAZL Au"]],
        paragraphs=15,
        numbers=[],
        footnotes=8,
        first="The petitioner is the printer, publisher and editor",
        last="enough on the subject in the connected c~se.",
        trailer="Petition allotved.",
    ),
    "1951_1_266_276": Expected(
        authors=[["MAHAJAN"]],
        paragraphs=33,
        numbers=[],
        footnotes=0,
        first="This is an appeal from a judJtment of the High Court",
        last="levy the same and pay it to the plaintiff.",
        trailer="Appeal allowed.",
    ),
    "S_1962_3_369_385": Expected(
        authors=[["AYYA:XGAR"]],  # Rajagopala Ayyangar J., as scanned
        paragraphs=31,
        numbers=[],
        footnotes=6,
        first="This appeal comes beforo. us by virtue of a certificate",
        last="there will be na order as to costs in the appeal.",
        trailer="Appeal allowed in part.",
    ),
    "1978_3_963_970": Expected(
        authors=[["DESAI"]],
        paragraphs=15,
        numbers=[],
        footnotes=10,
        first="The unsuccessful plaintiff, appellant in this appeal",
        last="This appeal accordingly fails and is dismissed with costs.",
        trailer="S.R. Appeal dismissed.",
    ),
    "1985_1_564_578": Expected(
        authors=[["CHANDRACHUD"]],
        paragraphs=41,
        numbers=[],
        footnotes=0,
        first="The petitioners, Prem Prakash and Dal Chand Anand,",
        last="the petition~rs the costs of these petitions.",
        trailer="M.L.A. Petitions allowed.",
    ),
    "S_1994_6_171_179": Expected(
        authors=[["DR. ANAND"]],
        paragraphs=8,
        numbers=[],
        footnotes=0,
        first="This appeal, by special leave, has been filed by Shivappa",
        last="released from custody forthwith unless required in any other case.",
        trailer="A.G. Appeal allowed.",
    ),
    "2005_3_1204_1209": Expected(
        authors=[[]],  # an order of the Court
        paragraphs=19,
        numbers=[],
        footnotes=0,
        first="These applications have been filed for clarification",
        last="disposed of with the aforementioned observations and directions.",
        trailer="R.P. Applications disposed of.",
    ),
    "2015_14_975_984": Expected(
        authors=[[]],
        paragraphs=12,
        numbers=[str(n) for n in range(1, 13)],
        footnotes=1,
        first="The adjudication on the merits of the controversy,",
        last="all matters having been collectively heard, are disposed of.",
        trailer="Nidhi Jain Matters disposed of.",
    ),
    "2023_12_370_380": Expected(
        authors=[[]],
        paragraphs=23,
        numbers=[str(n) for n in range(1, 24)],
        footnotes=4,
        first="This batch of cases raises two significant issues:",
        last="List the proceedings in the second week of January 2024.",
        trailer="Headnotes prepared by: Directions issued.",
    ),
    "2024_2_685_692": Expected(
        authors=[[]],
        paragraphs=19,
        numbers=["1", "2", "3"] + [f"3.{n}" for n in range(1, 9)] + [str(n) for n in range(4, 12)],
        footnotes=0,
        first="Leave granted.",
        last="Pending application(s), if any, stand disposed of.",
        trailer="Headnotes prepared by: Nidhi Jain Result of the case:",
    ),
}


@cache
def load(jid: str) -> tuple[ScrText, SplitJudgment]:
    cleaned = clean_scr((FIXTURES / f"{jid}.txt").read_text())
    return cleaned, split_judgment(cleaned.body)


def test_every_sample_has_expectations():
    manifest = yaml.safe_load((FIXTURES / "sources.yaml").read_text())
    ids = [j["id"] for j in manifest["judgments"]]
    assert sorted(ids) == sorted(EXPECTED)
    assert sorted(p.stem for p in FIXTURES.glob("*.txt")) == sorted(ids)


@pytest.mark.parametrize("jid", sorted(EXPECTED))
def test_sample(jid):
    want = EXPECTED[jid]
    cleaned, split = load(jid)
    assert cleaned.warnings == []
    assert [o.authors for o in split.opinions] == want.authors
    assert len(split.paragraphs) == want.paragraphs
    assert [p.court_number for p in split.paragraphs if p.court_number] == want.numbers
    assert len(cleaned.footnotes) == want.footnotes
    assert split.paragraphs[0].text.startswith(want.first)
    assert split.paragraphs[-1].text.endswith(want.last)
    assert cleaned.trailer.splitlines()[0] == want.trailer
    # Numbered judgments are numbered throughout; the rest warn that they are not.
    if want.numbers:
        assert all(p.court_number for p in split.paragraphs)
        assert split.warnings == []
    else:
        assert all("no court paragraph numbers" in w for w in split.warnings)


@pytest.mark.parametrize("jid", sorted(EXPECTED))
def test_no_page_furniture_in_body(jid):
    body = load(jid)[0].body
    assert not re.search(r"SUPREME\s+COURT\s+REPORTS|Supreme Court Reports|S\.\s*C\.\s*R\b", body)
    first_page, last_page = (int(n) for n in jid.split("_")[-2:])
    for line in body.splitlines():
        assert not re.fullmatch(r"[A-H]", line), line  # margin letters
        if m := re.fullmatch(r"\W*(\d{1,4})\W*", line):
            assert not first_page <= int(m[1]) <= last_page, line  # page numbers


def test_scanned_first_page_drops_the_previous_case():
    # Page 266 opens with the last paragraph of the case before.
    cleaned, _ = load("1951_1_266_276")
    assert "Jodha Singh" not in cleaned.header + cleaned.body
    assert cleaned.header.startswith("FATMA HAJI ALI MOHAMMAD HAJI")


def test_scanned_marginal_notes_are_dropped():
    # Each page of the scans carries the year, case title and judge in the margin.
    for jid, notes in [
        ("1950_1_594_605", ["Thappar", "Sastri", "Fazl"]),
        ("1951_1_266_276", ["Fatma", "Mahaj"]),
        ("S_1962_3_369_385", ["Kamechwar", "Prasad", "1962"]),
    ]:
        body = load(jid)[0].body
        for note in notes:
            assert note not in body, (jid, note)


def test_dissent_is_a_separate_opinion():
    _, split = load("1950_1_594_605")
    first_of_dissent = next(p for p in split.paragraphs if p.opinion == 1)
    assert first_of_dissent.text.startswith("For the reasons given by me in B1'ij Bhushan")
    # The majority ends with the order quashing the ban.
    last_of_majority = split.paragraphs[first_of_dissent.ordinal - 2]
    assert last_of_majority.text.endswith("is hereby quashed.")


def test_headnote_saying_per_judge_is_not_an_opinion():
    # The headnote reads "Per FAZL Au J.-Restrictions which s. 9 (1-A) ...".
    cleaned, split = load("1950_1_594_605")
    assert "Per FAZL Au J.-" in cleaned.header
    assert len(split.opinions) == 2


def test_footnotes_come_out_of_the_text():
    cleaned, split = load("2023_12_370_380")
    assert cleaned.footnotes == [
        "1 (2014) 10 SCC 635",
        "2 Surat Singh v Union of India (Writ Petition (C) No 316 of 2008)",
        "3 (1969) 2 SCC 734",
        "4 (2012) 10 SCC 603",
    ]
    assert "SCC" not in split.paragraph(2).text


def test_footnote_split_by_a_mid_page_running_head():
    # One PDF page holds the foot of page 967 and the head of page 968.
    cleaned, split = load("1978_3_963_970")
    assert "I) [1951] SCR 1125." in cleaned.footnotes
    assert not any("[1951] SCR 1125" in p.text for p in split.paragraphs)


def test_numbering_typo_and_sub_paragraphs():
    _, split = load("2023_12_370_380")
    para_22 = next(p for p in split.paragraphs if p.court_number == "22")
    assert para_22.text.startswith("The Union Ministry of Home Affairs shall furnish")  # printed "22 .The"
    _, split = load("2024_2_685_692")
    sub = next(p for p in split.paragraphs if p.court_number == "3.4")
    assert sub.text.startswith("Pursuant to the Re-Investigation Order")


def test_margin_letters_next_to_text_are_dropped():
    _, split = load("S_1994_6_171_179")
    text = " ".join(p.text for p in split.paragraphs)
    assert "he shall not be remanded to police custody" in text  # printed "be D remanded"
    assert "The conviction and sentence of the appellant is set aside" in text  # "conviction A"
    _, split = load("2015_14_975_984")
    assert '"collegium system". For the above purpose' in split.paragraph(1).text  # "0 system" in the scan


def test_text_that_only_looks_like_a_margin_letter_is_kept():
    # Current volumes print no margin letters, so a trailing initial stays.
    assert "Vishnu Unnikrishnan, C\nKranthi Kumar" in load("2023_12_370_380")[0].header
    # A headnote citation line is not mistaken for the title running head.
    assert "Jogendra Yadav v. State of Bihar, [2015] 9 SCR 69" in load("2024_2_685_692")[0].header


def test_order_of_the_court_without_author():
    cleaned, split = load("2005_3_1204_1209")
    assert cleaned.body.startswith("The following Order of the Court was delivered :")
    assert split.warnings == ["Opinion 1 has no court paragraph numbers; references use our own numbering."]


def test_quotation_after_an_indented_paragraph_start():
    _, split = load("S_1962_3_369_385")
    assert split.paragraph(2).text.startswith('"4~A.-Demonstrations and strikes.-')
    assert split.paragraph(3).text.startswith("Very soon after this rule was notified")


def test_list_marker_is_not_a_margin_letter():
    line = "    The rule provides for the following matters, which are set out in full:"
    text = "JUDGMENT\n\n" + "\n".join([line] * 6) + "\n    (a)     the first matter that the rule provides for\n"
    assert "(a) the first matter" in clean_scr(text).body
