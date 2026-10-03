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

The splitter was tested on synthetic judgments laid out like SC judgments (this environment can't reach the SC website). Tune it on real judgments before relying on it.

## Running it

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"

pytest                       # unit tests (schema tests run when DATABASE_URL is set)
python -m evals.run          # release gates
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
- Run the judgment splitter over 50 real judgments (old and new), fix what it gets wrong, and keep them as test fixtures. The same run gives the token counts for the cost estimate.
- Build the brief writer (Claude API) to produce claims in the `grounding.Claim` shape, and put every brief through `check_brief`.
- Build the first source adapter (the SC website or Digital SCR) behind `SourceStore`, once its terms are confirmed.
- Move the alias table into Postgres and resolve with `pg_trgm`. The Python matcher uses the same similarity measure, so results should line up.
- Add a curated list of known overrulings (Golak Nath, ADM Jabalpur, Koushal) to measure citator recall when Phase 4 starts.
