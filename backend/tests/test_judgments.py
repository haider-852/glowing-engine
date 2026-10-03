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


def test_line_break_hyphens_use_the_judgment_as_evidence():
    # "Govern- ment" is a line break: "Government" appears elsewhere. "Cross-
    # examination" keeps its hyphen for the same reason.
    text = (
        "JUDGMENT\n\n1. The Government replied. The cross-examination was brief. The Govern-\n"
        "ment relied on the cross-\nexamination of the witness.\n"
    )
    assert (
        split_judgment(text)
        .paragraph(1)
        .text.endswith("The Government relied on the cross-examination of the witness.")
    )


def test_line_break_hyphens_without_evidence():
    text = (
        "JUDGMENT\n\n1. The matter contri-\nbuted to the delay. The subject-\nmatter of the suit, the "
        "Munsif-\nMagistrate, the case-by-\ncase approach and the non-\ncognizable offence were "
        "threaten-\ning nobody. Not one matter of subject was raised.\n"
    )
    para = split_judgment(text).paragraph(1).text
    for expected in (
        "contributed",  # no evidence, not a compound: a syllable break
        "subject-matter",  # both halves are words the judgment uses
        "Munsif-Magistrate",  # a capital after the break
        "case-by-case",  # a link in a compound chain
        "non-cognizable",  # a compound prefix
        "threatening",  # a suffix
    ):
        assert expected in para, expected


def test_signature_blocks_as_the_website_prints_them():
    # Ellipsis characters, a mixed-case name, and "11th March, 2026".
    text = (
        "JUDGMENT\n\n1. The appeal is allowed.\n\n….……………………J.\n(J.B. Pardiwala)\n\n"
        "....................................... J.\n[K. V. VISWANATHAN]\n\nNew Delhi;\n11th March, 2026.\n"
    )
    j = split_judgment(text)
    assert [p.text for p in j.paragraphs] == ["The appeal is allowed."]


def test_order_of_the_court_after_a_split_decision():
    text = (
        "SINHA, J.—The appeal fails.\n\nDAYAL, J.—I dissent.\n\n"
        "By COURT : In view of the majority judgment the appeal is dismissed.\n"
    )
    j = split_judgment(text)
    assert [o.authors for o in j.opinions] == [["SINHA"], ["DAYAL"], []]
    assert j.paragraphs[-1].text == "In view of the majority judgment the appeal is dismissed."


def test_judge_quoted_by_name_is_not_a_new_opinion():
    # A name heading a quotation, whether the quotation opens with a quote
    # mark or with the quoted judgment's own paragraph number.
    text = (
        "JUDGMENT\n\nA.B. RAO, J.\n\n1. Counsel relied on two passages:\n\nA.K. Sikri, J.\n\n"
        "“219. Passive euthanasia occurs when treatment is withdrawn.”\n\nDr. D.Y. Chandrachud, J.\n\n"
        "333. I am also of the view that the directive is valid.\n\n2. We agree.\n"
    )
    j = split_judgment(text)
    assert [o.authors for o in j.opinions] == [["A.B. RAO"]]
    assert [p.court_number for p in j.paragraphs] == ["1", "2"]


def test_quoted_section_numbers_do_not_skip_the_numbering():
    # "5." and "7." are sections of the Act quoted in paragraph 3; the
    # judgment's own paragraph 4 follows the quotation.
    text = (
        "JUDGMENT\n\n1. Leave granted.\n\n2. The facts are brief.\n\n3. The relevant sections read:\n\n"
        "5. Procedure applicable to State Commissions.\n\n7. Power and procedure of the National Commission.\n\n"
        "4. A reading of these provisions is clear.\n"
    )
    j = split_judgment(text)
    assert [p.court_number for p in j.paragraphs] == ["1", "2", "3", "4"]
    assert "7. Power and procedure" in j.paragraph(3).text
    assert j.warnings == []


def test_headings_end_the_paragraph_before_them():
    text = (
        "JUDGMENT\n\n1. Leave granted.\n\nBRIEF FACTS\n\n2. The facts are these.\n\n(a) The first fact\n\n"
        "3. The second.\n\nDIAGNOSIS: GAUZE PIECES WITHIN A MASS\n\nThe report ends here.\n\n4. The last.\n"
    )
    j = split_judgment(text)
    assert [(p.court_number, p.text) for p in j.paragraphs[:5]] == [
        ("1", "Leave granted."),
        (None, "BRIEF FACTS"),
        ("2", "The facts are these."),
        (None, "(a) The first fact"),
        ("3", "The second.\n\nDIAGNOSIS: GAUZE PIECES WITHIN A MASS\n\nThe report ends here."),
    ]


def test_a_list_late_in_an_unnumbered_judgment_is_not_numbering():
    paras = "\n\n".join(f"Paragraph {n} of the judgment." for n in range(1, 8))
    text = f"MAHAJAN J.-{paras}\n\n1. Under section 8 the findings are final.\n\n2. Under section 34 they are not.\n"
    j = split_judgment(text)
    assert all(p.court_number is None for p in j.paragraphs)
