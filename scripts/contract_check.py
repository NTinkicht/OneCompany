#!/usr/bin/env python3
"""Deterministic, read-only contract/property/API/DB suite check (OC-P1-04 slice 10, #453).

Input: ``{"revision": 40-hex, "required_kinds": [kind], "suites": [{"id", "kind", "tests": [{"id", "status"}],
"seed": int, "examples": int}]}`` where kind is contract|property|api|db. A required kind without a suite,
an empty suite, a failed/errored/skipped test, or a property suite lacking an integer seed and positive
example count fails. No network, no writes, no clock.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HEX40 = re.compile(r"[0-9a-fA-F]{40}")
KINDS = {"contract", "property", "api", "db"}
STATUSES = {"pass", "fail", "error", "skipped"}


def _name(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def load_report(path: Path) -> dict:
    """Return the validated report; raise ValueError on anything malformed."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"report unreadable: {path.name} ({exc.__class__.__name__})") from exc
    if not isinstance(data, dict):
        raise ValueError("report is not an object")
    revision = data.get("revision")
    if not isinstance(revision, str) or not HEX40.fullmatch(revision):
        raise ValueError("report needs a 40-hex revision")
    required = data.get("required_kinds")
    if not isinstance(required, list) or not required:
        raise ValueError("report needs a non-empty required_kinds list")
    for kind in required:
        if not isinstance(kind, str) or kind not in KINDS:
            raise ValueError("required_kinds has an unknown kind")
    if len(set(required)) != len(required):
        raise ValueError("required_kinds has duplicates")
    suites = data.get("suites")
    if not isinstance(suites, list) or not suites:
        raise ValueError("report has no non-empty suites list")
    seen: set[str] = set()
    for suite in suites:
        if not isinstance(suite, dict):
            raise ValueError("suite is not an object")
        sid = suite.get("id")
        if not _name(sid):
            raise ValueError("suite needs a non-empty string id")
        if sid in seen:
            raise ValueError(f"duplicate suite id: {sid}")
        seen.add(sid)
        if not isinstance(suite.get("kind"), str) or suite["kind"] not in KINDS:
            raise ValueError(f"{sid} has unknown kind")
        tests = suite.get("tests")
        if not isinstance(tests, list):
            raise ValueError(f"{sid} tests must be a list")
        ids: set[str] = set()
        for test in tests:
            if not isinstance(test, dict):
                raise ValueError(f"{sid} test is not an object")
            if not _name(test.get("id")):
                raise ValueError(f"{sid} test needs a non-empty string id")
            if test["id"] in ids:
                raise ValueError(f"{sid} duplicate test id: {test['id']}")
            ids.add(test["id"])
            if not isinstance(test.get("status"), str) or test["status"] not in STATUSES:
                raise ValueError(f"{sid} test has unknown status")
        for field in ("seed", "examples"):
            if field in suite and not _int(suite[field]):
                raise ValueError(f"{sid} {field} must be an integer")
    return data


def evaluate(report: dict) -> dict:
    suites = sorted(report["suites"], key=lambda s: s["id"])
    present = {s["kind"] for s in suites}
    missing = [f"MISSING_KIND {k}" for k in sorted(set(report["required_kinds"]) - present)]
    empty, failed, skipped, unrepro = [], [], [], []
    for suite in suites:
        sid = suite["id"]
        if not suite["tests"]:
            empty.append(f"EMPTY_SUITE {sid}")
        for test in sorted(suite["tests"], key=lambda t: t["id"]):
            if test["status"] in ("fail", "error"):
                failed.append(f"FAILED {sid} {test['id']}")
            elif test["status"] == "skipped":
                skipped.append(f"SKIPPED {sid} {test['id']}")
        if suite["kind"] == "property" and not ("seed" in suite and suite.get("examples", 0) > 0):
            unrepro.append(f"UNREPRODUCIBLE {sid}")
    return {"suites": len(suites), "problems": missing + empty + failed + skipped + unrepro}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only contract/property/API/DB suite check.")
    parser.add_argument("report", help="suite report JSON file")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args(argv)
    try:
        result = evaluate(load_report(Path(args.report)))
    except ValueError as exc:
        print(f"contract-check: UNABLE TO VERIFY ({exc})", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"contract-check: {result['suites']} suites, {len(result['problems'])} problems")
        for item in result["problems"]:
            print(f"  {item}")
    return 1 if result["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
