"""The cleaner and splitter on judgment PDFs from the Supreme Court's website,
1954 to 2026, extracted with `pdftotext -layout` (tests/fixtures/sci,
sources.yaml).

The expected values were checked by reading each judgment's output against
the PDF. When a change to the cleaner or splitter moves one, read that
judgment again before updating it.
"""

import re
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import pytest
import yaml

from app.judgments import SplitJudgment, split_judgment
from app.sci import clean_sci
from app.scr import ScrText

FIXTURES = Path(__file__).parent / "fixtures" / "sci"


@dataclass
class Expected:
    authors: list[list[str]]
    paragraphs: int
    numbers: list[str] | int  # the court's numbers in order, or how many there are
    footnotes: int
    first: str  # start of the first paragraph
    last: str  # end of the last paragraph
    trailer: str | None  # first line after the judgment
    warnings: list[str] = field(default_factory=list)  # the splitter's


def no_numbers(opinions: int) -> list[str]:
    return [
        f"Opinion {n} has no court paragraph numbers; references use our own numbering." for n in range(1, opinions + 1)
    ]


def numbered(first: int, last: int) -> list[str]:
    return [str(n) for n in range(first, last + 1)]


EXPECTED = {
    # JUDIS text: the SCR report's text, with headnotes before "JUDGMENT:".
    "judis_900": Expected(
        authors=[["MEHR CHAND MAHAJAN"]],
        paragraphs=41,
        numbers=[],  # its closing "1." and "2." are a list, not paragraph numbers
        footnotes=0,
        first="The principal question canvassed in this case is whether",
        last="The petitioner will have his costs of these proceedings.",
        trailer="Writ issued,",
        warnings=no_numbers(1),
    ),
    # Five opinions: Kania C.J., "FAZL ALI J.--I agree.", Patanjali Sastri J.,
    # and Mahajan J. concurring in Mukherjea J.'s dissent.
    "judis_1248": Expected(
        authors=[["KANIA"], ["FAZL ALI"], ["PATANJALI SASTRI"], ["MAHAJAN"], ["MUKHERJEA"]],
        paragraphs=33,
        numbers=[],
        footnotes=0,
        first="This is an application for a writ of ’certiorari and prohibition under article 32",
        last="I would, therefore, allow the application and quash the externment order that has been passed "
        "against the petitioner.",
        trailer="Petition dismissed.",
        warnings=no_numbers(5),
    ),
    # Split bench: S.K. Das J. for three judges, a dissent, then the bench's order.
    "judis_3650": Expected(
        authors=[["S. K. DAS"], ["RAGHUBAR DAYAL"], []],
        paragraphs=72,
        numbers=[],
        footnotes=31,
        first="This is an appeal on a certificate of fitness granted by the High Court of Bombay",
        last="In view of the majority judgment the appeal is dismissed with costs.",
        trailer="Appeal dismissed.",
        warnings=no_numbers(3),
    ),
    # Printed "Subba Rao, C.J. This petition ..." and "Bachawat, J. The order ...".
    "judis_2500": Expected(
        authors=[["SUBBA RAO"], ["BACHAWAT"]],
        paragraphs=28,
        numbers=[],
        footnotes=10,
        first="This petition under Article 32 of the Constitution of India",
        last="I agree with the conclusions of the learned Chief Justice on other points and the order proposed by him.",
        trailer="V. P. S.",
        warnings=no_numbers(2),
    ),
    "judis_8000": Expected(
        authors=[[]],  # "The following Order of the Court was delivered:"
        paragraphs=13,
        numbers=[],
        footnotes=0,
        first="This writ petition filed in 1985 has been heard on different occasions",
        last="fixing the case for further hearing at 2.00 P.M. on 24th of April, 1989.",
        trailer="T.N.A.",
        warnings=no_numbers(1),
    ),
    "judis_28000": Expected(
        authors=[["Y.K. Sabharwal"]],
        paragraphs=12,
        numbers=[],
        footnotes=0,
        first="The validity of Rule 10(1) of the West Bengal Services",
        last="The appeal is allowed accordingly.",
        trailer=None,
        warnings=no_numbers(1),
    ),
    # Signed judgments.
    "judis_37000": Expected(
        authors=[["G.S. Singhvi"]],
        paragraphs=22,
        numbers=numbered(1, 22),
        footnotes=0,
        first="Leave granted.",
        last="The parties are left to bear their own costs.",
        trailer=None,
    ),
    "judis_43500": Expected(
        authors=[["R.F.NARIMAN"]],
        paragraphs=16,
        numbers=numbered(1, 16),
        footnotes=0,
        first="We have heard learned counsel for the parties.",
        last="Pending applications, if any, stand disposed of.",
        trailer="ITEM NO.61 COURT NO.11 SECTION IX",  # the Record of Proceedings
    ),
    # The first paragraph, "Leave granted.", is printed without its number.
    "sci_425932026_2026-09-29": Expected(
        authors=[[]],
        paragraphs=11,
        numbers=numbered(2, 11),
        footnotes=1,
        first="Leave granted.",
        last="Pending application(s), if any, shall stand rejected.",
        trailer=None,
        warnings=["Opinion 1: numbering starts at 2, not 1."],
    ),
    # 77 numbered paragraphs and five section headings.
    "sci_541182026_2026-09-28": Expected(
        authors=[["Mehta"]],
        paragraphs=82,
        numbers=numbered(1, 77),
        footnotes=15,
        first="Heard.",
        last="Pending application(s), if any, shall stand disposed of.",
        trailer="ITEM NO.5 COURT NO.2 SECTION II-A",
    ),
    # Pardiwala J. numbers 1-334, Viswanathan J. 1-65; the rest are headings,
    # epigraphs and the sentence introducing the index.
    "sci_609802025_2026-03-11": Expected(
        authors=[["J.B. PARDIWALA"], ["K. V. Viswanathan"]],
        paragraphs=456,
        numbers=numbered(1, 334) + numbered(1, 65),
        footnotes=65,
        first="For the convenience of exposition, this judgment is divided into the following parts:",
        last="it will be very naive to ignore this harsh reality.",
        trailer=None,
    ),
}


@cache
def load(jid: str) -> tuple[ScrText, SplitJudgment]:
    cleaned = clean_sci((FIXTURES / f"{jid}.txt").read_text())
    return cleaned, split_judgment(cleaned.body)


def text_of(split: SplitJudgment) -> str:
    return " ".join(p.text for p in split.paragraphs)


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
    numbers = [p.court_number for p in split.paragraphs if p.court_number]
    assert (numbers if isinstance(want.numbers, list) else len(numbers)) == want.numbers
    assert len(cleaned.footnotes) == want.footnotes
    assert split.paragraphs[0].text.startswith(want.first)
    assert split.paragraphs[-1].text.endswith(want.last)
    assert (cleaned.trailer.splitlines()[0] if cleaned.trailer else None) == want.trailer
    assert split.warnings == want.warnings


@pytest.mark.parametrize("jid", sorted(EXPECTED))
def test_no_page_furniture_in_the_text(jid):
    text = text_of(load(jid)[1])
    for furniture in (
        r"JUDIS\.NIC\.IN",
        r"Page \d+ of \d+",
        r"Signature Not Verified",
        r"Digitally signed",
        r"Reason:",
        r"RECORD OF PROCEEDINGS",
        r"IN THE SUPREME COURT OF INDIA",
        r"\.{6,}\s*\d+",  # a table of contents
        r"New Delhi;",
    ):
        assert not re.search(furniture, text), furniture


def test_judis_header_holds_the_report():
    cleaned, split = load("judis_3650")
    # The headnote's "Per Raghubar Dayal,J.-..." is not an opinion.
    assert "Per Raghubar Dayal,J.-(1) Any sum paid" in cleaned.header
    assert cleaned.header.startswith("PETITIONER:")
    assert "1962. December 12.-The following judgments were delivered." in cleaned.header
    assert len(split.opinions) == 3


def test_judis_bench_with_five_opinions():
    cleaned, split = load("judis_1248")
    assert cleaned.header.endswith("1950. May 26. The following judgments were delivered:--")
    assert [len([p for p in split.paragraphs if p.opinion == o.index]) for o in split.opinions] == [12, 1, 1, 1, 18]
    assert split.paragraph(13).text == "I agree."  # Fazl Ali J., after a line that fills the column
    assert cleaned.trailer.splitlines() == [
        "Petition dismissed.",
        "Agent for the petitioner: Ganpat Rai.",
        "Agent for the opposite party: P.A. Mehta.",
    ]


def test_judis_dissent_and_order_of_the_court():
    _, split = load("judis_3650")
    dissent = next(p for p in split.paragraphs if p.opinion == 1)
    assert dissent.text.startswith("I have had the advantage of perusing the majority judgment")
    majority_end = split.paragraph(dissent.ordinal - 1)
    assert majority_end.text.endswith("The appeal is accordingly dismissed with costs.")
    order = split.paragraphs[-1]
    assert (order.opinion, split.opinions[order.opinion].authors) == (2, [])


def test_judis_footnotes_come_out_of_the_text():
    cleaned, split = load("judis_3650")
    assert cleaned.footnotes[:2] == ["(1) (1931) 6 Tax Cas. 605. 634.", "(2) (1924) 9 Tax Cas. 48."]
    assert "Tax Cas. 605" not in text_of(split)
    # Several notes on one line are separate footnotes.
    cleaned, _ = load("judis_2500")
    assert "(5) 68 L.E.D. 999." in cleaned.footnotes and "(6) 86 L. E.d. 1302." in cleaned.footnotes


def test_judis_title_case_authors_named_in_the_preamble():
    cleaned, split = load("judis_2500")
    assert "was delivered by SUBBA RAO, C.J. BACHAWAT, J." in cleaned.header
    assert cleaned.body.startswith("SUBBA RAO, C.J. This petition")
    concurrence = next(p for p in split.paragraphs if p.opinion == 1)
    assert concurrence.text.startswith("The order of Khanna, J. dismissing the Writ petition")


def test_judis_text_cut_at_a_fixed_width_is_rejoined():
    text = text_of(load("judis_8000")[1])
    for rejoined in (
        "has been heard on different occasions",  # "heard" / "on"
        "several orders and directions have been made",  # "ha" / "ve"
        "not exceeding 30 to 35",  # "30" / "to"
        "the Registry of the Court by 7th April, 1989",  # "7" / "th"
        "Notice be issued to the learned Attorney General to appear",
    ):
        assert rejoined in text, rejoined
    assert "  " not in text  # justification spaces are collapsed


def test_judis_page_breaks_do_not_break_paragraphs():
    _, split = load("judis_3650")
    para = next(p for p in split.paragraphs if p.text.startswith("The relevant facts lie within a narrow compass."))
    assert "the assessee received a notice from the firm dated December 29, 1947" in para.text


def test_signature_stamp_beside_the_text():
    _, split = load("sci_425932026_2026-09-29")
    assert split.paragraph(3).text == (
        "The allegation was that 32 bullocks were carried in a truck from Keduwa and the same was proceeding "
        "towards Odisha, when it was detained by PW3, a Head Constable, who had received information of such "
        "transport being made. The cattle were seized, and the driver and the cleaner were arrested. Together "
        "with them, a Bolero car, which was moving in front of the truck, was also detained, alleging that the "
        "car was escorting the truck. Four persons travelling in the car were also arrested, one of whom was the "
        "petitioner herein."
    )
    cleaned, _ = load("sci_425932026_2026-09-29")
    assert cleaned.footnotes == ["1 For brevity, ‘the Act’"]


def test_double_spacing_is_not_paragraph_breaks():
    _, split = load("judis_37000")
    assert split.paragraph(2).text == (
        "This appeal is directed against the order of the National Consumer Disputes Redressal Commission (for "
        "short, ‘the National Commission’) whereby the order passed by the Maharashtra State Consumer Disputes "
        "Redressal Commission (for short, ‘the State Commission’) dismissing the complaint filed by the "
        "respondent as barred by limitation was reversed and the case was remitted for disposal of the complaint "
        "on merits."
    )


def test_quoted_sections_are_not_paragraph_numbers():
    # Paragraph 13 quotes sections 12, 18, 22 and 24A of the Act; paragraph 14 follows.
    _, split = load("judis_37000")
    para_13 = next(p for p in split.paragraphs if p.court_number == "13")
    assert "18. Procedure applicable to State Commissions" in para_13.text
    assert "22. Power and procedure applicable to the National Commission" in para_13.text
    para_14 = next(p for p in split.paragraphs if p.court_number == "14")
    assert para_14.text.startswith("A reading of the above noted provisions makes it clear")


def test_quoted_capitals_stay_in_their_paragraph():
    _, split = load("judis_37000")
    para_6 = next(p for p in split.paragraphs if p.court_number == "6")
    assert para_6.text.endswith("LYMPH NODES – REACTIVE SINUS HISTIOCYTOSIS.”")


def test_section_headings_are_paragraphs_of_their_own():
    _, split = load("sci_541182026_2026-09-28")
    assert [p.text for p in split.paragraphs if p.court_number is None] == [
        "BRIEF FACTS",
        "SUBMISSIONS ON BEHALF OF THE APPELLANT-STATE, INFORMANT AND INDIAN MEDICAL ASSOCIATION",
        "SUBMISSIONS ON BEHALF OF THE RESPONDENT ACCUSED",
        "ANALYSIS AND DISCUSSION",
        "CONCLUSION",
    ]
    assert split.paragraph(10).text.endswith("run by outlaws.")
    assert split.paragraph(12).court_number == "11"


def test_record_of_proceedings_is_the_trailer():
    cleaned, split = load("judis_43500")
    assert "RECORD OF PROCEEDINGS" in cleaned.trailer
    assert "(Signed reportable judgment is placed on the file)" in cleaned.trailer
    assert "(KURIAN JOSEPH)" in cleaned.body  # the signatures stay with the judgment


def test_concurrence_on_its_own_cover_page():
    cleaned, split = load("sci_609802025_2026-03-11")
    # The cover page between the majority's date and the concurrence is dropped.
    assert "New Delhi;\n\n11th March, 2026.\nJUDGMENT\n\nK. V. Viswanathan, J." in cleaned.body
    majority = [p for p in split.paragraphs if p.opinion == 0]
    assert majority[-1].text == "We direct the Registry to send one copy each of our judgments to all the High Courts."
    concurrence = next(p for p in split.paragraphs if p.opinion == 1 and p.court_number == "1")
    assert concurrence.text.startswith("I have had the benefit of reading the erudite judgment")
    assert split.label(concurrence) == "Viswanathan J., para 1"


def test_judges_quoted_by_name_are_not_opinions():
    # "A.K. Sikri, J." above a quotation from Common Cause (2018).
    _, split = load("sci_609802025_2026-03-11")
    para_23 = next(p for p in split.paragraphs if p.opinion == 0 and p.court_number == "23")
    assert "substantiate her contention:\n\nA.K. Sikri, J.\n\n“219. Passive euthanasia occurs" in para_23.text


def test_tables_of_contents_are_dropped():
    cleaned, split = load("sci_609802025_2026-03-11")
    assert "INDEX" not in cleaned.body
    assert "BRIEF FACTS ...." not in cleaned.body
    assert split.paragraph(2).text.startswith("“God asks no man whether he will accept life.")


def test_footnotes_restart_in_a_separate_opinion():
    cleaned, _ = load("sci_609802025_2026-03-11")
    assert [int(n.split()[0]) for n in cleaned.footnotes] == list(range(1, 57)) + list(range(1, 10))
    assert cleaned.footnotes[56] == "1 (2023) 14 SCC 131"


def test_headings_and_subheadings_end_the_paragraph_before():
    _, split = load("sci_609802025_2026-03-11")
    headings = [p.text for p in split.paragraphs if p.opinion == 0 and p.court_number is None]
    assert "(A). FACTUAL MATRIX" in headings
    assert "(h) Best interest of the patient in India" in headings
    assert (
        "(4) WHAT ARE THE FURTHER STEPS TO BE UNDERTAKEN IN THE EVENT THAT A DECISION TO WITHDRAW OR WITHHOLD "
        "MEDICAL TREATMENT IS ARRIVED AT?"
    ) in headings
