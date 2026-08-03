"""Run the behavioural evals.

    cd backend && python -m evals.run                  # every scenario, 3 runs each
    cd backend && python -m evals.run --only crashloop # substring filter on name
    cd backend && python -m evals.run --runs 5

Costs real LLM tokens and is non-deterministic by design. Never wire into CI.
"""
import argparse
import asyncio
import json
import pathlib
import statistics
from typing import Any, Dict, List

from evals.harness import Scenario, load_scenarios, run_scenario
from evals.scoring import score

SCENARIO_DIR = pathlib.Path(__file__).parent / "scenarios"
OUTPUT = pathlib.Path(__file__).parent / "last-run.json"


async def _run_one(scenario: Scenario, runs: int) -> Dict[str, Any]:
    attempts: List[Dict[str, Any]] = []
    for i in range(runs):
        trace = await run_scenario(scenario)
        checks = score(scenario, trace)
        # Advisory checks (e.g. no_unknown_names) are still computed and still
        # recorded below, but never decide the verdict — only blocking checks do.
        attempts.append({
            "run": i + 1,
            "passed": all(c.passed for c in checks if not c.advisory),
            "checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail, "advisory": c.advisory}
                for c in checks
            ],
            "calls": [name for name, _ in trace.calls],
            "answer": trace.answer,
            "error": trace.error,
        })
    passes = sum(1 for a in attempts if a["passed"])
    return {
        "name": scenario.name,
        "known_failing": scenario.known_failing,
        "runs": runs,
        "passes": passes,
        "pass_rate": passes / runs if runs else 0.0,
        "attempts": attempts,
    }


def _report(results: List[Dict[str, Any]], threshold: float) -> int:
    print(f"\n{'scenario':<44} {'pass':>7}  verdict")
    print("-" * 70)
    failed = 0
    graded = [r for r in results if not r.get("known_failing")]
    for r in results:
        known = r.get("known_failing", False)
        ok = r["pass_rate"] >= threshold
        if known:
            verdict = "KNOWN"
        else:
            verdict = "PASS" if ok else "FAIL"
            failed += 0 if ok else 1
        print(f"{r['name']:<44} {r['passes']}/{r['runs']:<5} {verdict}")
        # Known-deferred scenarios print their detail unconditionally (never
        # hidden, per evals/scenarios/README.md) even on a run where they
        # happen to score at/above threshold; ordinary scenarios only print
        # it when they actually failed, as before.
        if known or not ok:
            # Show every distinct blocking failing check across the attempts, once each.
            seen = set()
            for attempt in r["attempts"]:
                for c in attempt["checks"]:
                    if c["advisory"]:
                        continue
                    if not c["passed"] and (key := (c["name"], c["detail"])) not in seen:
                        seen.add(key)
                        print(f"    - {c['name']}: {c['detail']}")
        # Advisory checks never affect the verdict above, but must still surface —
        # print them under their own heading regardless of pass/fail.
        advisory_seen = set()
        for attempt in r["attempts"]:
            for c in attempt["checks"]:
                if c["advisory"] and not c["passed"] and (key := (c["name"], c["detail"])) not in advisory_seen:
                    advisory_seen.add(key)
                    print(f"    ~ [advisory] {c['name']}: {c['detail']}")
    print("-" * 70)
    # Known-failing (deliberately deferred) scenarios are excluded from the
    # headline entirely -- they are graded nowhere, only displayed above.
    if graded:
        rates = [r["pass_rate"] for r in graded]
        print(f"{len(graded) - failed}/{len(graded)} scenarios at or above "
              f"{threshold:.0%}; median pass rate {statistics.median(rates):.0%}")
    else:
        print("no graded scenarios (all matched scenarios are known-failing)")
    if len(results) != len(graded):
        print(f"({len(results) - len(graded)} known-failing scenario(s) excluded above — see KNOWN rows)")
    return failed


async def _main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="substring filter on scenario name")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--threshold", type=float, default=1.0,
                    help="fraction of runs that must pass (default 1.0 — flaky is failing)")
    args = ap.parse_args()

    scenarios = [s for s in load_scenarios(SCENARIO_DIR) if args.only in s.name]
    if not scenarios:
        print(f"no scenarios matching {args.only!r}")
        return 1

    results = [await _run_one(s, args.runs) for s in scenarios]
    OUTPUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
    failed = _report(results, args.threshold)
    print(f"\nfull output: {OUTPUT}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
