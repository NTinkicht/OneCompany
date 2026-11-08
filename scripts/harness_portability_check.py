#!/usr/bin/env python3
"""Deterministic, read-only harness portability check (OC-P1-05 slice 1, #457).

Input: ``{"revision": 40-hex, "required_backends": [id], "backends": [{"id", "fixture_digest",
"result_digest", "status": pass|fail|error|skipped, "sandbox_escape_attempt": refused|allowed|not_run,
"stale_context_attempt": rejected|accepted|not_run, "crash_recovery": recovered|lost|not_run}]}``.
Fails on a missing required backend, a non-pass status, differing fixture or result digests across
backends, an escape not refused, stale context not rejected, or a crash not recovered. Anything
``not_run`` fails closed. No network, no writes, no clock.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HEX40 = re.compile(r"[0-9a-fA-F]{40}")
HEX64 = re.compile(r"[0-9a-fA-F]{64}")
STATUSES = {"pass", "fail", "error", "skipped"}
ESCAPE = {"refused", "allowed", "not_run"}
STALE = {"rejected", "accepted", "not_run"}
CRASH = {"recovered", "lost", "not_run"}


def _name(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _digest(value: object) -> bool:
    return isinstance(value, str) and bool(HEX64.fullmatch(value))


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
    required = data.get("required_backends")
    if not isinstance(required, list) or not required or not all(_name(b) for b in required):
        raise ValueError("report needs a non-empty required_backends list of names")
    if len(set(required)) != len(required):
        raise ValueError("required_backends has duplicates")
    backends = data.get("backends")
    if not isinstance(backends, list) or not backends:
        raise ValueError("report has no non-empty backends list")
    seen: set[str] = set()
    for entry in backends:
        if not isinstance(entry, dict):
            raise ValueError("backend is not an object")
        bid = entry.get("id")
        if not _name(bid):
            raise ValueError("backend needs a non-empty string id")
        if bid in seen:
            raise ValueError(f"duplicate backend id: {bid}")
        seen.add(bid)
        for field in ("fixture_digest", "result_digest"):
            if not _digest(entry.get(field)):
                raise ValueError(f"{bid} {field} must be a 64-hex digest")
        for field, allowed in (("status", STATUSES), ("sandbox_escape_attempt", ESCAPE),
                               ("stale_context_attempt", STALE), ("crash_recovery", CRASH)):
            if not isinstance(entry.get(field), str) or entry[field] not in allowed:
                raise ValueError(f"{bid} has unknown {field}")
    return data


def evaluate(report: dict) -> dict:
    backends = sorted(report["backends"], key=lambda b: b["id"])
    present = {b["id"] for b in backends}
    problems = [f"MISSING_BACKEND {b}" for b in sorted(set(report["required_backends"]) - present)]
    for b in backends:
        bid = b["id"]
        if b["status"] != "pass":
            problems.append(f"NOT_PASSING {bid} {b['status']}")
        if b["sandbox_escape_attempt"] != "refused":
            problems.append(f"SANDBOX_ESCAPE_NOT_REFUSED {bid} {b['sandbox_escape_attempt']}")
        if b["stale_context_attempt"] != "rejected":
            problems.append(f"STALE_CONTEXT_NOT_REJECTED {bid} {b['stale_context_attempt']}")
        if b["crash_recovery"] != "recovered":
            problems.append(f"CRASH_NOT_RECOVERED {bid} {b['crash_recovery']}")
    if len({b["fixture_digest"].lower() for b in backends}) > 1:
        problems.append("FIXTURE_MISMATCH backends ran different fixtures")
    if len({b["result_digest"].lower() for b in backends}) > 1:
        problems.append("RESULT_DIVERGENCE same fixture produced different results")
    return {"backends": len(backends), "problems": problems}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only harness portability check.")
    parser.add_argument("report", help="portability report JSON file")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args(argv)
    try:
        result = evaluate(load_report(Path(args.report)))
    except ValueError as exc:
        print(f"harness-check: UNABLE TO VERIFY ({exc})", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"harness-check: {result['backends']} backends, {len(result['problems'])} problems")
        for item in result["problems"]:
            print(f"  {item}")
    return 1 if result["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
