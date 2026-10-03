"""Run the test set and enforce the release gates.

    python -m evals.run            # print the report; exit 1 if a gate fails
    python -m evals.run --json     # machine-readable report

Gates (from the roadmap, Phase 5):

* fake_cases_verified == 0 — a trap query must never end in "verified". Any
  failure blocks release.
* trap_queries_resolved == 0 — the resolver must not pick a case for a trap.
* correct_case_rate >= 0.95 — real queries find the right case (or, for
  ambiguous names, ask with the right options).
"""

from __future__ import annotations

import argparse
import json
import operator
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.cases import load_cases
from app.pipeline import NullSourceStore, SourceStore, lookup
from app.resolver import ResolutionStatus, Resolver
from app.verification import VerificationStatus

QUERIES = Path(__file__).resolve().parent / "queries.yaml"


@dataclass(frozen=True)
class Gate:
    metric: str
    op: str
    target: float

    def passes(self, value: float) -> bool:
        return {"==": operator.eq, ">=": operator.ge, "<=": operator.le}[self.op](value, self.target)


GATES = [
    Gate("fake_cases_verified", "==", 0),
    Gate("trap_queries_resolved", "==", 0),
    Gate("correct_case_rate", ">=", 0.95),
]


@dataclass
class Report:
    metrics: dict[str, float]
    failures: list[dict] = field(default_factory=list)
    gates: list[dict] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(g["passed"] for g in self.gates)


def run_eval(
    store: SourceStore | None = None, queries_path: Path = QUERIES, resolver: Resolver | None = None
) -> Report:
    resolver = resolver or Resolver(load_cases())
    store = store or NullSourceStore()
    rows = yaml.safe_load(queries_path.read_text())["queries"]

    real = traps = correct = trap_resolved = fake_verified = 0
    failures = []
    for row in rows:
        result = lookup(row["query"], resolver, store)
        res = result.resolution
        got = [c.case.id for c in res.candidates]
        is_trap = row["kind"].startswith("trap_")
        if is_trap:
            traps += 1
            problems = []
            if res.status is ResolutionStatus.RESOLVED:
                trap_resolved += 1
                problems.append(f"resolved to {got[0]}")
            if result.verification.status is VerificationStatus.VERIFIED:
                fake_verified += 1
                problems.append("marked VERIFIED")
            ok = not problems
        else:
            real += 1
            expect = row["expect"]
            if expect["status"] == "resolved":
                ok = res.status is ResolutionStatus.RESOLVED and got[0] == expect["cases"][0]
            else:
                ok = res.status is ResolutionStatus.AMBIGUOUS and set(expect["cases"]) <= set(got)
            correct += ok
            problems = [] if ok else [f"expected {expect['status']} {expect['cases']}"]
        if not ok:
            failures.append(
                {
                    "query": row["query"],
                    "kind": row["kind"],
                    "status": res.status.value,
                    "candidates": got,
                    "problems": problems,
                }
            )

    metrics = {
        "queries": len(rows),
        "real_queries": real,
        "trap_queries": traps,
        "correct_case_rate": round(correct / real, 4) if real else 0.0,
        "trap_queries_resolved": trap_resolved,
        "fake_cases_verified": fake_verified,
    }
    gates = [
        {
            "metric": g.metric,
            "op": g.op,
            "target": g.target,
            "value": metrics[g.metric],
            "passed": g.passes(metrics[g.metric]),
        }
        for g in GATES
    ]
    return Report(metrics, failures, gates)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = run_eval()
    if args.json:
        print(json.dumps({"metrics": report.metrics, "gates": report.gates, "failures": report.failures}, indent=2))
    else:
        m = report.metrics
        print(f"{m['queries']} queries ({m['real_queries']} real, {m['trap_queries']} traps)\n")
        for g in report.gates:
            mark = "PASS" if g["passed"] else "FAIL"
            print(f"  [{mark}] {g['metric']} = {g['value']}  (target {g['op']} {g['target']})")
        if report.failures:
            print("\nFailures:")
            for f in report.failures:
                print(
                    f"  - [{f['kind']}] {f['query']!r}: {'; '.join(f['problems'])} "
                    f"(got {f['status']} {f['candidates']})"
                )
        print("\nRelease gates passed." if report.passed else "\nRelease BLOCKED.")
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
