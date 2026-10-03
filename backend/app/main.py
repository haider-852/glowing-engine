from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, Query

from .cases import load_cases
from .citations import find_citations, plausibility_issues
from .pipeline import DISCLAIMER, NullSourceStore, SourceStore, lookup
from .resolver import Candidate, Resolution, Resolver
from .verification import VerificationResult

app = FastAPI(title="Case Verification and Briefing API", version="0.1.0")


@lru_cache
def get_resolver() -> Resolver:
    return Resolver(load_cases())


def get_store() -> SourceStore:
    return NullSourceStore()


QueryText = Annotated[str, Query(min_length=1, max_length=500)]
ResolverDep = Annotated[Resolver, Depends(get_resolver)]
StoreDep = Annotated[SourceStore, Depends(get_store)]


def _candidate(c: Candidate) -> dict:
    return {
        "id": c.case.id,
        "title": c.case.title,
        "year": c.case.year,
        "bench_strength": c.case.bench_strength,
        "citations": [cit.canonical for cit in c.case.citations],
        "score": c.score,
        "notes": c.notes,
    }


def _resolution(r: Resolution) -> dict:
    return {
        "status": r.status.value,
        "message": r.message,
        "citations": [c.canonical for c in r.citations],
        "candidates": [_candidate(c) for c in r.candidates],
    }


def _verification(v: VerificationResult) -> dict:
    return {
        "status": v.status.value,
        "reasons": v.reasons,
        "differences": [{"field": d.field, "values": d.values} for d in v.differences],
        "checked": v.checked,
        "sources": v.sources,
    }


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/citations/parse")
def parse(q: QueryText) -> dict:
    return {
        "citations": [
            {
                "canonical": c.canonical,
                "reporter": c.reporter,
                "year": c.year,
                "volume": c.volume,
                "page": c.page,
                "court": c.court,
                "series": c.series,
                "supplement": c.supplement,
                "issues": plausibility_issues(c),
            }
            for c in find_citations(q)
        ]
    }


@app.get("/api/resolve")
def resolve(q: QueryText, resolver: ResolverDep) -> dict:
    return _resolution(resolver.resolve(q))


@app.get("/api/lookup")
def lookup_case(q: QueryText, resolver: ResolverDep, store: StoreDep) -> dict:
    result = lookup(q, resolver, store)
    return {
        "query": q,
        "resolution": _resolution(result.resolution),
        "verification": _verification(result.verification),
        "disclaimer": DISCLAIMER,
    }
