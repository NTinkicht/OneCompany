#!/usr/bin/env python3
"""Deterministic, read-only negative-regression report (OC-P1-04 slice 3, #439).

Inputs: a regressions file ``{"regressions": [{"id", "test", "failed_before_fix": bool}]}`` and a
run file ``{"results": {"<test id>": "pass|fail|error|skip"}}``. A regression is ``proven`` only
when ``failed_before_fix`` is literally true and its test passed in the run. Everything else is
reported (unproven, failing or missing) and the exit status stays non-zero. No network, no writes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from flaky_report import load_run  # noqa: E402


def load_regressions(path: Path) -> list[dict]:
    """Return validated regression records; raise ValueError on anything malformed."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"regressions file unreadable: {path.name} ({exc.__class__.__name__})") from exc
    items = data.get("regressions") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError(f"regressions file has no regressions list: {path.name}")
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("regression record is not an object")
        rid, test = item.get("id"), item.get("test")
        if not isinstance(rid, str) or not rid or not isinstance(test, str) or not test:
            raise ValueError("regression record needs non-empty string id and test")
        if not isinstance(item.get("failed_before_fix"), bool):
            raise ValueError(f"regression {rid}: failed_before_fix must be a boolean")
        if rid in seen:
            raise ValueError(f"duplicate regression id: {rid}")
        seen.add(rid)
    return items


def classify(regressions: list[dict], run: dict[str, str]) -> dict:
    out = {"proven": [], "unproven": [], "failing": [], "missing": []}
    for item in sorted(regressions, key=lambda r: r["id"]):
        outcome = run.get(item["test"])
        if outcome is None:
            out["missing"].append(item["id"])
        elif outcome != "pass":
            out["failing"].append(item["id"])
        elif item["failed_before_fix"] is not True:
            out["unproven"].append(item["id"])
        else:
            out["proven"].append(item["id"])
    out["total"] = len(regressions)
    return out


def exit_code(result: dict) -> int:
    return 0 if len(result["proven"]) == result["total"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only negative-regression proof report.")
    parser.add_argument("regressions", help="regressions JSON file")
    parser.add_argument("run", help="run JSON file")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args(argv)
    try:
        result = classify(load_regressions(Path(args.regressions)), load_run(Path(args.run)))
    except ValueError as exc:
        print(f"regression-report: UNABLE TO VERIFY ({exc})", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"regression-report: {len(result['proven'])}/{result['total']} regressions proven")
        for key, label in (("unproven", "UNPROVEN"), ("failing", "FAILING"), ("missing", "MISSING")):
            for rid in result[key]:
                print(f"  {label} {rid}")
    return exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
