#!/usr/bin/env python3
"""Deterministic, read-only flaky-test report (OC-P1-04 slice 2, #437).

Takes two or more JSON run files of the form ``{"results": {"<test id>": "pass|fail|error|skip"}}``
and classifies every test as stable_pass, stable_fail, flaky or insufficient. Quarantine
without bypass: flaky tests are listed as quarantine candidates for human review but are
never treated as passes, so the exit status stays non-zero. No network, no writes, no clock.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

OUTCOMES = frozenset({"pass", "fail", "error", "skip"})
BAD = frozenset({"fail", "error"})


def load_run(path: Path) -> dict[str, str]:
    """Return the test->outcome map of one run file; raise ValueError on anything malformed."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"run file unreadable: {path.name} ({exc.__class__.__name__})") from exc
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, dict) or not results:
        raise ValueError(f"run file has no results object: {path.name}")
    for test, outcome in results.items():
        if not isinstance(test, str) or not test or outcome not in OUTCOMES:
            raise ValueError(f"run file has an invalid test id or outcome: {path.name}")
    return dict(results)


def classify(runs: list[dict[str, str]]) -> dict:
    """Classify tests across runs; a test missing from a run counts as an error in that run."""
    names = sorted({name for run in runs for name in run})
    out = {"stable_pass": [], "stable_fail": [], "flaky": [], "insufficient": [], "skipped": []}
    for name in names:
        outcomes = [run.get(name, "error") for run in runs]
        executed = [o for o in outcomes if o != "skip"]
        if not executed:
            out["skipped"].append(name)
        elif len(runs) < 2:
            out["insufficient"].append(name)
        elif all(o in BAD for o in executed):
            out["stable_fail"].append(name)
        elif any(o in BAD for o in executed):
            out["flaky"].append(name)
        else:
            out["stable_pass"].append(name)
    out["runs"] = len(runs)
    out["quarantine_candidates"] = list(out["flaky"])
    return out


def exit_code(result: dict) -> int:
    """Zero only when nothing is failing, flaky or unqualified; flaky is never a pass."""
    return 1 if result["stable_fail"] or result["flaky"] or result["insufficient"] else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only flaky-test report over repeated run files.")
    parser.add_argument("runs", nargs="+", help="JSON run files")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args(argv)
    try:
        result = classify([load_run(Path(p)) for p in args.runs])
    except ValueError as exc:
        print(f"flaky-report: UNABLE TO VERIFY ({exc})", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"flaky-report: {result['runs']} run(s), {len(result['stable_pass'])} stable pass")
        for key, label in (("stable_fail", "STABLE_FAIL"), ("flaky", "FLAKY"), ("insufficient", "INSUFFICIENT")):
            for name in result[key]:
                print(f"  {label} {name}")
        if result["quarantine_candidates"]:
            print("  quarantine candidates need human review; they still fail this report")
    return exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
