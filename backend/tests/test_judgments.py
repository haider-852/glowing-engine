"""Splitter tests on synthetic judgments laid out like real SC judgments."""

from app.judgments import split_judgment

MODERN = """\
REPORTABLE
IN THE SUPREME COURT OF INDIA
CIVIL APPELLATE JURISDICTION
CIVIL APPEAL NO. 1234 OF 2019

ASHA DEVI                                   ...APPELLANT(S)
VERSUS
STATE OF EXAMPLE                            ...RESPONDENT(S)

J U D G M E N T

A.B. RAO, J.

1. This appeal arises from a judgment of the High Court dated
12 March 2018 dismissing the writ petition.

2. The facts are brief. The appellant applied for a licence
in 2015, which was refused.

Signature Not Verified
Digitally signed by SOME OFFICER
Date: 2019.05.01 16:30:12 IST
Reason:
3

3. Section 5 of the Act provides:

"5. No licence shall be refused except for
reasons recorded in writing."

The refusal recorded no reasons.

3.1 The High Court did not consider this.

4. The appeal is allowed.

..............................J.
[A.B. RAO]

..............................J.
[C. MEHTA]

New Delhi;
May 1, 2019

J U D G M E N T

Dr D.E. Iyer, J.

1. I agree with the conclusion but add a few words on self-
defence of the statutory scheme.

2. The Act must be read as a whole.

..............................J.
[D.E. IYER]
"""

OLD_REPORT = """\
The Judgment of the Court was delivered by

SIKRI, C.J.—The facts of this case are set out in the
judgment of my learned brother and need not be repeated.

The first question is whether the amendment is valid.
In my view it is.

HEGDE, J.—I agree with the learned Chief Justice
on the first question.

On the second question I take a different view.
"""


def test_modern_judgment_opinions_and_numbers():
    j = split_judgment(MODERN)
    assert [o.authors for o in j.opinions] == [["A.B. RAO"], ["Dr D.E. Iyer"]]
    assert [(p.opinion, p.court_number) for p in j.paragraphs] == [
        (0, "1"),
        (0, "2"),
        (0, "3"),
        (0, "3.1"),
        (0, "4"),
        (1, "1"),
        (1, "2"),
    ]
    assert [p.ordinal for p in j.paragraphs] == list(range(1, 8))
    assert "CIVIL APPEAL NO. 1234 OF 2019" in j.header
    assert j.warnings == []


def test_modern_judgment_text_is_clean():
    j = split_judgment(MODERN)
    second = j.paragraph(2).text
    assert second == "The facts are brief. The appellant applied for a licence in 2015, which was refused."
    # Page furniture, signatures and the place/date line are dropped.
    joined = " ".join(p.text for p in j.paragraphs)
    for noise in ("Signature Not Verified", "Digitally signed", "[A.B. RAO]", "New Delhi", "May 1, 2019"):
        assert noise not in joined
    assert "self-defence" in j.paragraph(6).text


def test_block_quote_stays_in_its_paragraph():
    # The quoted "5. No licence ..." must not be read as paragraph 5, and the
    # sentence after the quote belongs to paragraph 3.
    third = split_judgment(MODERN).paragraph(3)
    assert third.court_number == "3"
    assert '"5. No licence shall be refused except for reasons recorded in writing."' in third.text
    assert third.text.endswith("The refusal recorded no reasons.")


def test_labels_name_the_author_when_there_are_several_opinions():
    j = split_judgment(MODERN)
    assert j.label(j.paragraph(2)) == "Rao J., para 2"
    assert j.label(j.paragraph(7)) == "Iyer J., para 2"


def test_old_report_with_inline_authors_and_no_numbers():
    j = split_judgment(OLD_REPORT)
    assert [o.authors for o in j.opinions] == [["SIKRI"], ["HEGDE"]]
    assert [(p.opinion, p.court_number) for p in j.paragraphs] == [(0, None), (0, None), (1, None), (1, None)]
    assert j.paragraph(1).text.startswith("The facts of this case")
    assert j.label(j.paragraph(1)) == "[1]"
    assert any("no court paragraph numbers" in w for w in j.warnings)


def test_numbering_gap_is_reported():
    text = "JUDGMENT\n\n1. First.\n\n2. Second.\n\n5. Fifth.\n"
    j = split_judgment(text)
    assert [p.court_number for p in j.paragraphs] == ["1", "2", "5"]
    assert any("jumps from 2 to 5" in w for w in j.warnings)


def test_out_of_sequence_number_is_not_a_paragraph():
    # "1950." at the start of a wrapped line is a year, not paragraph 1950.
    text = "JUDGMENT\n\n1. The Constitution came into force on 26 January\n1950. It was adopted earlier.\n"
    j = split_judgment(text)
    assert len(j.paragraphs) == 1
    assert "1950. It was adopted" in j.paragraph(1).text


def test_text_without_markers_is_one_opinion():
    j = split_judgment("First paragraph.\n\nSecond paragraph.\n")
    assert len(j.opinions) == 1
    assert [p.text for p in j.paragraphs] == ["First paragraph.", "Second paragraph."]
    assert "No judgment heading" in j.warnings[0]


def test_sentence_ending_in_judge_name_is_not_an_author_line():
    text = "JUDGMENT\n\n1. This view was taken in an earlier case by\nKrishna Iyer, J.\n\n2. We agree.\n"
    j = split_judgment(text)
    assert len(j.opinions) == 1
    assert [p.court_number for p in j.paragraphs] == ["1", "2"]
    assert j.paragraph(1).text.endswith("by Krishna Iyer, J.")
    assert j.warnings == []


def test_scanned_report_author_lines():
    # Scanned reports print a hyphen for the dash and often drop the comma;
    # later reports drop the dash too.
    text = (
        "MAHAJAN J.-This is an appeal.\n\nIt fails.\n\n"
        "FAZL ALI J.-I dissent.\n\n"
        "CHANDRACHUD, C. J. The petitioners are members of a scheduled caste.\n\n"
        "DR. ANAND, J. This appeal is allowed.\n"
    )
    j = split_judgment(text)
    assert [o.authors for o in j.opinions] == [["MAHAJAN"], ["FAZL ALI"], ["CHANDRACHUD"], ["DR. ANAND"]]
    assert [p.text for p in j.paragraphs][2:] == [
        "I dissent.",
        "The petitioners are members of a scheduled caste.",
        "This appeal is allowed.",
    ]


def test_no_dash_author_line_needs_capitals():
    # "Krishna Iyer, J. The ..." in running text is a citation, not an opinion.
    text = "JUDGMENT\n\n1. We agree.\n\nKrishna Iyer, J. The view was approved.\n"
    j = split_judgment(text)
    assert len(j.opinions) == 1


def test_order_passed_marker():
    j = split_judgment("The following Order of the Court was passed:\n\nThe applications are disposed of.\n")
    assert len(j.opinions) == 1
    assert j.paragraph(1).text == "The applications are disposed of."
    assert not any("No judgment heading" in w for w in j.warnings)


def test_numbers_without_dots():
    # Some judgments number paragraphs "1 The order ...". A wrapped line that
    # starts with the next number is not a paragraph.
    text = "ORDER\n\n1 The order of this Court sets out the background under Section\n2 of the Act.\n\n2 We agree.\n"
    j = split_judgment(text)
    assert [p.court_number for p in j.paragraphs] == ["1", "2"]
    assert j.paragraph(1).text.endswith("Section 2 of the Act.")


def test_numbering_typos_and_lone_numbers():
    # "22 .The" is a typo in a 2023 order; plain pdftotext puts "1." alone on its line.
    text = "ORDER\n\n1.\n\nLeave granted.\n\n2 .The appeal is allowed.\n"
    j = split_judgment(text)
    assert [(p.court_number, p.text) for p in j.paragraphs] == [
        ("1", "Leave granted."),
        ("2", "The appeal is allowed."),
    ]
