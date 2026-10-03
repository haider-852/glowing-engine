"""Grounding checks on a synthetic judgment.

The judgment text is made up; the cases it cites are real names from the seed
table, used only to test name and citation handling.
"""

import pytest

from app.cases import CaseEntry
from app.citations import parse_citation
from app.grounding import Claim, case_names, check_brief, quotations, quote_in
from app.judgments import split_judgment

JUDGMENT = split_judgment("""\
J U D G M E N T

A.B. RAO, J.

1. The appellant challenges the refusal of a licence under Section 5 of the
Example Act, 1990.

2. In Kesavananda Bharati v. State of Kerala, (1973) 4 SCC 225, this Court
held that Parliament cannot alter the “basic structure” of the
Constitution. That principle was applied in Minerva Mills Ltd. v. Union of
India.

3. The appellant also relies on Ramesh Chandra v. Example Board, which is
not reported.

4. Section 5 requires that “no licence shall be refused except for reasons
recorded in writing”. No reasons were recorded. The refusal is set aside
and the appeal is allowed.
""")

SUBJECT = CaseEntry(
    id="asha-devi-1990",
    title="Asha Devi v. State of Example",
    year=1990,
    citations=(parse_citation("[1990] 2 SCR 100"),),
)


@pytest.fixture
def check(resolver):
    def run(text, paragraphs, section="holding"):
        report = check_brief([Claim(section, text, paragraphs)], JUDGMENT, resolver, SUBJECT)
        return report.checks[0]

    return run


def test_judgment_fixture_splits_as_expected():
    assert [p.court_number for p in JUDGMENT.paragraphs] == ["1", "2", "3", "4"]


def test_grounded_claim_is_kept(check):
    c = check('Section 5 requires that "no licence shall be refused except for reasons recorded in writing".', [4])
    assert c.kept and not c.flags, c.problems


def test_claim_without_paragraph_is_dropped(check):
    assert check("The appeal was allowed.", []).problems == ["The claim cites no paragraph."]


def test_claim_citing_missing_paragraph_is_dropped(check):
    assert "do not exist" in check("The appeal was allowed.", [4, 9]).problems[0]


def test_altered_quotation_is_dropped(check):
    c = check('The Act says "no licence shall be refused without reasons".', [4])
    assert "does not appear in the judgment" in c.problems[0]


def test_quotation_from_another_paragraph_is_dropped_with_a_pointer(check):
    c = check('The Court relied on the "basic structure" doctrine.', [1])
    assert "is in para 2, not the cited paragraphs" in c.problems[0]


def test_quotation_with_ellipsis(check):
    c = check('Section 5 says "no licence shall be refused ... in writing".', [4])
    assert c.kept, c.problems


def test_quotation_spanning_line_breaks_and_curly_quotes(check):
    c = check("It protects the “basic structure of the Constitution”? No: “basic structure”.", [2])
    assert "basic structure of the Constitution" in c.problems[0]
    assert len(c.problems) == 1


def test_case_named_in_cited_paragraph_and_table_is_kept(check):
    c = check("The Court followed Kesavananda Bharati v. State of Kerala, (1973) 4 SCC 225.", [2])
    assert c.kept and not c.flags, c.problems


def test_case_in_paragraph_but_not_in_table_is_flagged(check):
    c = check("The appellant relied on Ramesh Chandra v. Example Board.", [3])
    assert c.kept
    assert "not in our case table yet" in c.flags[0]


def test_invented_case_is_dropped(check):
    c = check("The Court also followed Sunita Rao v. State of Goa.", [2])
    assert "not in the cited paragraphs" in c.problems[0]


def test_real_case_not_in_cited_paragraph_is_dropped(check):
    # Golak Nath is real and in our table, but this judgment never mentions it:
    # the brief writer took it from memory.
    c = check("The Court overruled Golak Nath v. State of Punjab.", [2])
    assert "not in the cited paragraphs" in c.problems[0]


def test_citation_not_in_cited_paragraph_is_dropped(check):
    c = check("Kesavananda Bharati is reported at AIR 1973 SC 1461.", [2])
    assert "AIR 1973 SC 1461 is not in the cited paragraphs" in c.problems[0]


def test_brief_may_always_name_the_case_itself(check):
    c = check("In Asha Devi v. State of Example, [1990] 2 SCR 100, the appeal was allowed.", [4])
    assert c.kept, c.problems


def test_report_sections():
    claims = [
        Claim("facts", "The appellant was refused a licence.", [1]),
        Claim("holding", "The appeal was allowed.", [4]),
        Claim("ratio", 'Reasons must be "recorded in writing".', [9]),
    ]
    report = check_brief(claims, JUDGMENT)
    assert len(report.kept) == 2 and len(report.dropped) == 1
    assert "ratio" in report.empty_sections()
    assert "facts" not in report.empty_sections()


def test_quote_helpers():
    assert quotations('He said “yes” and "no".') == ["yes", "no"]
    assert quote_in("a ... d", "a b c d")
    assert not quote_in("d ... a", "a b c d")


@pytest.mark.parametrize(
    "text, names",
    [
        ("In Kesavananda Bharati v. State of Kerala, the Court held.", ["Kesavananda Bharati v. State of Kerala"]),
        ("In 1973, Golak Nath v. State of Punjab was overruled.", ["Golak Nath v. State of Punjab"]),
        ("See Justice K.S. Puttaswamy v. Union of India.", ["Justice K.S. Puttaswamy v. Union of India"]),
        ("It relied on Minerva Mills Ltd. v. Union of India (1980).", ["Minerva Mills Ltd. v. Union of India"]),
        ("No case is named here.", []),
    ],
)
def test_case_names(text, names):
    assert case_names(text) == names
