"""Query in, resolved case and verification status out.

The source store is the only thing that talks to case-law sources. Until the
retriever exists, `NullSourceStore` returns nothing, so every lookup ends in
"could not verify". That is the intended behaviour: the tool never answers
from memory.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .cases import CaseEntry
from .resolver import Resolution, Resolver
from .verification import SourceRecord, VerificationResult, VerificationStatus, verify

DISCLAIMER = "This is a research aid, not legal advice. Always read the original judgment before relying on it."


class SourceStore(Protocol):
    def records_for(self, case: CaseEntry) -> list[SourceRecord]: ...


class NullSourceStore:
    """No retriever yet: no records for any case."""

    def records_for(self, case: CaseEntry) -> list[SourceRecord]:
        return []


@dataclass
class LookupResult:
    resolution: Resolution
    verification: VerificationResult


def lookup(query: str, resolver: Resolver, store: SourceStore) -> LookupResult:
    resolution = resolver.resolve(query)
    case = resolution.case
    if case is None:
        verification = VerificationResult(
            VerificationStatus.COULD_NOT_VERIFY,
            ["The query did not resolve to a single case."],
        )
    else:
        verification = verify(store.records_for(case), expected=case)
    return LookupResult(resolution, verification)
