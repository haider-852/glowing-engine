# Case Verification and Briefing

A research aid for Indian Supreme Court judgments. A user types a case name or
citation and gets the case confirmed against two or more sources, a brief tied
to paragraph numbers, and how later cases have treated it. When a step fails,
the tool says **could not verify** rather than guessing.

This repository holds the first building blocks from the roadmap (Phases 3 and
5). There is no retriever, brief writer or citator yet, but the checks a brief
must pass already exist.

## What's here

| Path | What it does |
| --- | --- |
| `backend/app/citations.py` | Parses SCC (including Supp and Cri/L&S/Tax), AIR, SCR, SCALE, JT and INSC neutral citations into canonical form, and rejects citations that can't be real (a future year, AIR SC before 1950, SCC before 1969). |
| `backend/app/resolver.py` | Matches a typed name or citation to one case, asks "Did you mean…?" when several fit, and never picks a case when the name, year or citation disagree. |
| `backend/app/verification.py` | The rules for **Verified / Partly verified / Could not verify** (below). |
| `backend/app/judgments.py` | Splits a judgment's text into opinions and paragraphs. Keeps the court's own numbering where there is one, gives every paragraph our own number, drops signatures and page furniture, and warns about gaps in the numbering. |
| `backend/app/scr.py` | Cleans the text of a Digital SCR PDF (`pdftotext -layout`) for the splitter: separates headnotes, counsel and the editor's notes from the judgment, and removes running heads, page numbers, margin letters, marginal notes and footnotes. |
| `backend/app/sci.py` | The same for judgment PDFs from the SC website, in both of its layouts: JUDIS text (to about 2009) and the signed judgment (from about 2010). Removes the "Signature Not Verified" stamp, "Page 3 of 22", running lines, tables of contents, footnotes and the Record of Proceedings, and finds paragraphs in double-spaced text. |
| `backend/tests/fixtures/scr/` | Fourteen Digital SCR reports, 1950 to 2024, as extracted text, with their sources in `sources.yaml`. `scripts/fetch_scr_samples.py` downloads them again. |
| `backend/tests/fixtures/sci/` | Eleven judgment PDFs from the SC website, 1950 to 2026, as extracted text, with their sources in `sources.yaml`. `scripts/fetch_sci_samples.py` downloads them again. |
| `backend/app/grounding.py` | Checks a brief against the judgment. Drops any claim that cites no paragraph, misquotes, or names a case or citation that isn't in the paragraphs it cites. Flags cases that aren't in our table yet. |
| `backend/app/pipeline.py` | Query → resolution → verification. The source store is the only part that will talk to case-law sources. |
| `backend/app/main.py` | FastAPI: `/api/citations/parse`, `/api/resolve`, `/api/lookup`. |
| `backend/data/seed_cases.yaml` | 13 landmark cases to develop against. **Typed from memory and unchecked.** See below. |
| `backend/evals/` | The start of the Phase 5 test set (52 queries, 16 of them traps) and the release gates. |
| `db/migrations/001_core.sql` | Postgres schema: cases, aliases, citations, source documents, opinions, paragraphs, citator edges, legislative overrides, briefs, error reports. |

## What "verified" means here

A case is **Verified** only when:

1. at least two records come from **independent origins** (a site republishing the SC website's text is a copy, not a second witness);
2. at least one record is **official** (the SC website or Digital SCR);
3. all titles match each other and the case the user asked for;
4. the decision date is reported by two or more records, and they agree;
5. the bench, and every citation in the same reporter, agree. That includes the citations in our own table.

If 1 to 3 fail, the result is **Could not verify**. If only 4 or 5 fail, it's **Partly verified**, listing the fields that differ.

This tightens the roadmap's definition. A neutral-citation match is required only where a neutral citation exists, because most landmark cases predate 2023.

Until a retriever exists, every lookup ends in "could not verify". That's intended: the tool never answers from memory.

## Release gates

`python -m evals.run` runs the test set and exits non-zero if any gate fails. CI runs it on every push.

| Gate | Target |
| --- | --- |
| Fake case marked verified | 0 (blocks release) |
| Trap query resolved to a case | 0 |
| Correct case found | ≥ 95% |

One test runs the whole test set against a fake retriever that "confirms" any case it's asked about. Traps still fail, because they're stopped at resolution, before verification.

## The seed data is not a source

`seed_cases.yaml` was typed from memory so there's something to test against. Every entry has `checked_against_source: false`. Before the alias table is used for real, check each entry's title, year, bench strength and citations against Digital SCR or the SC website, then flip the flag one entry at a time.

## Paragraph numbers

Many older judgments have no court-assigned paragraph numbers, and SCC's numbering is protected editorial work (*EBC v. D.B. Modak*). The schema gives every paragraph its own stable `ordinal`. It keeps `court_number` only where the court's text numbers the paragraph, plus the official `scr_page` where known.

## Checks every brief must pass

`grounding.check_brief` runs on every generated brief before it's shown or cached:

| Problem | Result |
| --- | --- |
| Claim cites no paragraph, or one that doesn't exist | Dropped |
| Quotation isn't word for word in the cited paragraphs (`...` may mark gaps) | Dropped, with a pointer if the quote is in another paragraph |
| Names a case or gives a citation that isn't in the cited paragraphs | Dropped, even if the case is real: it came from the model's memory |
| Names a case that is in the cited paragraphs but not in our table | Kept, flagged for review |
| A section has nothing left | That section shows "could not verify" |

The brief may always name the judgment being briefed. Whether a paragraph supports a claim's *meaning* needs a separate model check, which isn't built yet.

## The splitter on real judgments

The splitter has been tuned on 25 real judgments from 1950 to 2026, in three layouts:

- **Fourteen Digital SCR reports** (`tests/fixtures/scr`, `tests/test_scr.py`): three scanned reports from 1950 to 1962, five from the typed volumes of 1978 to 2015, and six from 2022 to 2024. Five have separate opinions (Romesh Thappar's dissent, three split benches from 2022 and 2023, and a concurrence in Arvind Kejriwal v. CBI). The others include an order of the Court with no author, a first page that opens with the end of the previous case, footnotes, and sub-paragraphs numbered "3.1.".
- **Six JUDIS texts from the SC website** (`tests/fixtures/sci`, `tests/test_sci.py`): judgments of 1950 to 2006 as the website's archive holds them, the SCR report's text keyed in, with the headnotes in front. Three have separate opinions: N.B. Khare (five opinions, two dissenting), CIT v. E.D. Sheppard (a dissent and then the bench's order) and Ghulam Sarwar (a concurrence).
- **Five signed judgments from the SC website**, 2010 to 2026: the layout with "J U D G M E N T", signature blocks, "Signature Not Verified" and "New Delhi;" and the date. They include Harish Rana v. Union of India (2026, 338 pages, with a concurrence), an order with no author, and two with the court master's Record of Proceedings appended.

The tests check each judgment's authors, paragraph count, numbering, footnotes and boundaries, and that no page furniture is left in the text. Every expected value was checked by reading the output against the PDF's text.

### Where the PDFs come from

`www.sci.gov.in` is reachable from the build environment now. `digiscr.sci.gov.in` and `main.sci.gov.in` are not, because they no longer exist: public DNS has no record of either. Digital SCR moved to [`scr.sci.gov.in/scrsearch`](https://scr.sci.gov.in/scrsearch/).

The SC website's judgment searches and Digital SCR's search all need a CAPTCHA, and we did not get around it. The 2026 judgments come from the home page's "Latest Judgments" list and the "Landmark Judgment Summaries" page. The older ones come from the archive the old site's search linked to (`api.sci.gov.in/jonew/judis/<n>.pdf`), found by trying numbers one at a time. `sources.yaml` gives each one's URL, citations and why it was chosen, and `scripts/fetch_sci_samples.py` downloads them again, one at a time with a pause. The site's copyright policy allows reproduction with the source acknowledged.

The Digital SCR reports still come from the [AWS Open Data mirror](https://indian-supreme-court-judgments.s3.amazonaws.com). That's fine for test fixtures, but the mirror is a copy: it can't be a verification source.

**We have not compared the mirror's PDFs with the official ones.** `scr.sci.gov.in` shows a report's PDF only after a search behind a CAPTCHA. `scripts/compare_scr_copies.py` compares PDFs downloaded by hand with the mirror's copies. What could be checked is the mirror's metadata, against the SC website's own records for the six judgments in both. The decision dates and SCR citations agree. But for four of the six, the mirror's bench lists one judge: for example, S.K. Das J. alone for Sheppard, where four judges sat.

### What tuning found

- **The reporter's material wraps the judgment.** Headnotes can say "Per FAZL ALI J.—...", which the splitter would read as an opinion. `scr.clean_scr` and `sci.clean_sci` find where the judgment starts ("The Judgment of the Court was delivered by", "JUDGMENT / ORDER OF THE SUPREME COURT", the first author line) and ends (the editor's "Appeal dismissed.", initials and agents; on the website, the Record of Proceedings).
- **Blank lines don't mark paragraphs.** SCR marks them by indentation. JUDIS text is flush left, so a paragraph ends where a line falls short. Signed judgments are often double-spaced, but their cover pages and appended orders are not, so the cleaner measures the spacing page by page. Extraction must use `pdftotext -layout`: plain extraction loses indentation and margins.
- **Page furniture differs by layout:** SCR has running heads, margin letters and marginal notes. JUDIS has its own page head and the SCR page numbers, with that page's footnotes just above them. Signed judgments have "Page 3 of 22", a running line with the case number, tables of contents, and a cover page before a separate opinion. The 2026 judgments also carry the "Signature Not Verified" stamp, printed in the margin on the same lines as the text; the 2010 and 2016 ones don't.
- **JUDIS texts from the 1980s were cut at a fixed width.** The end of each long line is printed at the start of the next ("ha" / "ve"). The cleaner rejoins them using the judgment's own words: "have" occurs in it, so "ha" + "ve" is one word, while "heard" + "on" stays two.
- **Author lines vary more than expected:** "MAHAJAN J.-This" (no comma, hyphen), "CHANDRACHUD, C. J. The petitioners" (no dash), a name alone on its line, and in JUDIS "Subba Rao, C.J. This petition" in title case. The splitter only trusts the title-case form when the reporter's preamble names that judge as delivering a judgment, because "Krishna Iyer, J. The view ..." is usually a citation. Numbering also appears as "1 The order" (no dot) and "22 .The" (a typo). After a split decision comes "By COURT : In view of the majority judgment ...", an opinion with no author.
- **Numbers and names that aren't what they look like:**
  - A judgment that quotes sections 18 and 22 of an Act looks as if it jumps from paragraph 13 to 18. The splitter now accepts a jump only if the number it expects doesn't turn up further on.
  - Harish Rana quotes earlier judges under their names ("A.K. Sikri, J."), which look like author lines. A name followed by a quotation, or by a paragraph number too high to start an opinion, is a quotation's heading.
  - A list numbered "1." and "2." near the end of an unnumbered judgment isn't paragraph numbering.
- **Headings are paragraphs of their own.** "BRIEF FACTS", "(A). FACTUAL MATRIX" and "(h) Best interest of the patient in India" used to be glued to the end of the paragraph before. A heading counts as one only when the next paragraph number follows it, so quoted capitals such as "DIAGNOSIS: GAUZE PIECES ..." stay where they are. This added four heading paragraphs to each of two SCR samples. It also exposed a running head that `clean_scr` had left inside a paragraph of the 2015 sample; that is now removed.
- **Separate opinions restart their numbering, and the first paragraph is often printed without its number** (both opinions in Kejriwal, the dissent in Gangadhar Nayak, "Leave granted." in a 2026 order). The splitter reports this as "numbering starts at 2", which is what the page shows; the paragraph still gets our own number. Footnote numbers restart in a separate opinion too.
- **Scanned reports (before about 1970) are OCR text with errors:** "AYYA:XGAR, J." for Ayyangar J., "FAZL Au J." for Fazl Ali J., "beforo" for "before". The brief checker's word-for-word quote test will fail on garbled words.
  - **JUDIS text is much cleaner than this OCR.** N.B. Khare (1950) is in both the mirror and JUDIS. Each text has about 3,760 words of three letters or more. 93 distinct words appear only in the SCR scan's text, nearly all garbled ("argiied", "restnct", "whicl"). Only 30 appear only in JUDIS, mostly real words the OCR mangled, with a few typos ("consitution", "grouuds").
  - The SCR scan of N.B. Khare also yields only three of its five opinions: the splitter misses Patanjali Sastri J.'s and Fazl Ali J.'s one-line "I agree.", which is printed beside a margin note. JUDIS gives all five.
- **Words split across lines need the judgment as a dictionary.** The fourteen SCR samples have 269 hyphens at line ends, mostly syllable breaks ("Govern-ment") with some compounds ("non-cognizable", "examination-in-chief"). The splitter checks which form the same judgment uses elsewhere. With no evidence, it keeps the hyphen after a prefix like "non-", before a capital, or between two words the judgment uses alone ("subject-matter"). About six still come out wrong, mostly in garbled scans ("certiorariwould"), plus "reinvestigation" and "subclause" where the judgment never uses the word mid-line.
- **Still not handled:**
  - Footnote reference numbers stay in the text ("Act, 20041", "respondent No. 710").
  - Tables come out as fragments, and margin letters next to capitalised words ("A It may be") are kept.
  - In 1980s JUDIS text, justification spaces survive inside a date ("28.2. 1989"), and a cut name in the counsel list stays split ("Bhattachary a").
  - An epigraph printed as verse comes out as two paragraphs.
- **Size, for the cost estimate:** judgment text runs about 300 words, or roughly 450 tokens, per SCR page (characters ÷ 4; the API's token counter gives exact figures). Signed judgments use large type and are often double-spaced: 150 to 250 words a page. So page counts overstate them: Harish Rana's 338 pages are 85,000 words, about 132,000 tokens. The SCR samples' judgments are 1,800 to 12,400 words; the website's run from 750 to 85,000.

## Running it

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

pytest                       # unit tests (schema tests run when DATABASE_URL is set)
python -m evals.run          # release gates
python scripts/fetch_scr_samples.py   # download the Digital SCR samples again (needs pdftotext)
python scripts/fetch_sci_samples.py   # download the SC website samples again
python scripts/compare_scr_copies.py 1950_1_594_605=~/Downloads/romesh.pdf   # official copy vs mirror
uvicorn app.main:app --reload
# http://localhost:8000/api/lookup?q=Shah%20Bano
```

Schema (needs Postgres 16 with pgvector):

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db/migrations/001_core.sql
DATABASE_URL=... pytest tests/test_schema.py
```

## Next steps

- Check the seed entries against official sources, and grow the alias table to the 500 most-cited cases.
- Grow `evals/queries.yaml` toward the 150–200 labelled cases, and add every user error report.
- Compare two or three official Digital SCR PDFs with the mirror's copies. Download them by hand from `scr.sci.gov.in` (its search needs a CAPTCHA) and run `scripts/compare_scr_copies.py`.
- Take the splitter's test set from 25 to 50 judgments. Include more split benches in the signed layout: Harish Rana is the only one so far, because the website's search needs a CAPTCHA and the open lists rarely have them.
- Use JUDIS text rather than OCR of the SCR scans for judgments before about 2000. Keep the SCR page numbers, which JUDIS prints, so references can still be given by SCR page.
- Build the brief writer (Claude API) to produce claims in the `grounding.Claim` shape, and put every brief through `check_brief`.
- Build the first source adapter (the SC website or Digital SCR) behind `SourceStore`. Both put search behind a CAPTCHA, so the adapter needs an agreed route (an API or bulk data from the Registry or NIC), not scraping.
- Move the alias table into Postgres and resolve with `pg_trgm`. The Python matcher uses the same similarity measure, so results should line up.
- Add a curated list of known overrulings (Golak Nath, ADM Jabalpur, Koushal) to measure citator recall when Phase 4 starts.
