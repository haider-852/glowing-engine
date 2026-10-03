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
| `backend/tests/fixtures/scr/` | Fourteen real judgments, 1950 to 2024, as extracted text, with their sources in `sources.yaml`. `scripts/fetch_scr_samples.py` downloads them again. |
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

The splitter has been tuned on fourteen Digital SCR judgments: three scanned reports from 1950 to 1962, five from the typed volumes of 1978 to 2015, and six from 2022 to 2024. Five have separate opinions (Romesh Thappar's dissent, three split benches from 2022 and 2023, and a concurrence in Arvind Kejriwal v. CBI). The others include an order of the Court with no author, a first page that opens with the end of the previous case, footnotes, and sub-paragraphs numbered "3.1.". `tests/test_scr.py` checks each one's authors, paragraph count, numbering, footnotes and boundaries.

Neither `www.sci.gov.in` nor `digiscr.sci.gov.in` was reachable from the build environment (its network policy blocks both), so the PDFs came from the [AWS Open Data mirror](https://indian-supreme-court-judgments.s3.amazonaws.com) of Digital SCR. That's fine for test fixtures, but the mirror is a copy: it can't be a verification source.

What tuning found:

- **The reporter's material wraps the judgment.** Headnotes can say "Per FAZL ALI J.—...", which the splitter would read as an opinion. `scr.clean_scr` finds where the judgment starts ("The Judgment of the Court was delivered by", "JUDGMENT / ORDER OF THE SUPREME COURT") and ends (the editor's "Appeal dismissed.", agents, "Headnotes prepared by").
- **Paragraphs are marked by indentation, not blank lines,** and margin notes can only be told from text by position. So extraction must use `pdftotext -layout`; plain extraction loses both.
- **Author lines vary more than expected:** "MAHAJAN J.-This" (no comma, hyphen), "CHANDRACHUD, C. J. The petitioners" (no dash), and in current volumes a name alone on its line, sometimes straight after a page break. Numbering also appears as "1 The order" (no dot) and "22 .The" (a typo).
- **Separate opinions restart their numbering, and the first paragraph is often printed without its number** (both opinions in Kejriwal, the dissent in Gangadhar Nayak). The splitter reports this as "numbering starts at 2", which is what the page shows; the paragraph still gets our own number.
- **Scanned reports (before about 1970) are OCR text with errors:** "AYYA:XGAR, J." for Ayyangar J., "FAZL Au J." for Fazl Ali J., "beforo" for "before". Author names from these need checking against the bench, and the brief checker's word-for-word quote test will fail on garbled words. Scanned judgments need a cleaner text source (or re-OCR) before briefs are written from them.
- **Words split across lines need the judgment as a dictionary.** The fourteen samples have 269 hyphens at line ends, mostly syllable breaks ("Govern-ment") with some compounds ("non-cognizable", "examination-in-chief"). The splitter checks which form the same judgment uses elsewhere. With no evidence, it keeps the hyphen after a prefix like "non-", before a capital, or between two words the judgment uses alone ("subject-matter"). About six still come out wrong, mostly in garbled scans ("certiorariwould"), plus "reinvestigation" and "subclause" where the judgment never uses the word mid-line.
- **Still not handled:** footnote reference numbers stay in the text ("Maharashtra 1."); tables come out as fragments; margin letters next to capitalised words ("A It may be") are kept.
- **The mirror's metadata is unreliable:** Romesh Thappar lists only Kania C.J. as the bench (six judges sat, and Patanjali Sastri J. wrote the judgment).
- **Size, for the cost estimate:** judgment text runs about 300 words, or roughly 450 tokens, per SCR page (characters ÷ 4; the API's token counter gives exact figures). The fourteen samples are 6 to 41 pages; their judgments are 1,800 to 12,400 words.

None of the samples is a judgment PDF from the SC website itself, which has a different layout (signature blocks, "J U D G M E N T"). The splitter's tests for that layout are still synthetic.

## Running it

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

pytest                       # unit tests (schema tests run when DATABASE_URL is set)
python -m evals.run          # release gates
python scripts/fetch_scr_samples.py   # download the sample judgments again (needs pdftotext)
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
- Take the splitter's test set from 14 to 50 judgments, and add judgment PDFs from the SC website, once `www.sci.gov.in` and `digiscr.sci.gov.in` are allowed in the environment's network settings. Include a bench with three or more opinions.
- Find a better text source for scanned judgments (before about 1970), or re-OCR them, before writing briefs from them.
- Build the brief writer (Claude API) to produce claims in the `grounding.Claim` shape, and put every brief through `check_brief`.
- Build the first source adapter (the SC website or Digital SCR) behind `SourceStore`, once its terms are confirmed.
- Move the alias table into Postgres and resolve with `pg_trgm`. The Python matcher uses the same similarity measure, so results should line up.
- Add a curated list of known overrulings (Golak Nath, ADM Jabalpur, Koushal) to measure citator recall when Phase 4 starts.
