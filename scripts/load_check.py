#!/usr/bin/env python3
"""Deterministic, read-only load-result check (OC-P1-04 slice 7, #447).

Input: ``{"revision": 40-hex, "scenarios": [{"id", "requests", "errors", "duration_ms", "p95_ms"}]}``.
Each scenario must stay inside the error budget (permille), the p95 latency ceiling and the minimum
throughput. Integer arithmetic only. No network, no writes, no clock.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HEX40 = re.compile(r"[0-9a-f]{40}")


def _int(value: object, name: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def load_scenarios(path: Path) -> list[dict]:
    """Return validated scenarios; raise ValueError on anything malformed."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"report unreadable: {path.name} ({exc.__class__.__name__})") from exc
    if not isinstance(data, dict):
        raise ValueError("report is not an object")
    revision = data.get("revision")
    if not isinstance(revision, str) or not HEX40.fullmatch(revision):
        raise ValueError("report needs a 40-hex revision")
    items = data.get("scenarios")
    if not isinstance(items, list) or not items:
        raise ValueError("report has no non-empty scenarios list")
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("scenario is not an object")
        sid = item.get("id")
        if not isinstance(sid, str) or not sid.strip():
            raise ValueError("scenario needs a non-empty string id")
        if sid in seen:
            raise ValueError(f"duplicate scenario id: {sid}")
        seen.add(sid)
        requests = _int(item.get("requests"), f"{sid} requests", 1)
        errors = _int(item.get("errors"), f"{sid} errors", 0)
        if errors > requests:
            raise ValueError(f"{sid} errors exceed requests")
        _int(item.get("duration_ms"), f"{sid} duration_ms", 1)
        _int(item.get("p95_ms"), f"{sid} p95_ms", 0)
    return items


def evaluate(scenarios: list[dict], max_error_permille: int, max_p95_ms: int, min_rps: int) -> dict:
    breaches: dict[str, list[str]] = {}
    for s in sorted(scenarios, key=lambda x: x["id"]):
        found = []
        if s["errors"] * 1000 > max_error_permille * s["requests"]:
            found.append("error_budget")
        if s["p95_ms"] > max_p95_ms:
            found.append("latency")
        if s["requests"] * 1000 < min_rps * s["duration_ms"]:
            found.append("throughput")
        if found:
            breaches[s["id"]] = found
    return {"scenarios": len(scenarios), "breaches": breaches}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only load-result budget check.")
    parser.add_argument("report", help="load report JSON file")
    parser.add_argument("--max-error-permille", type=int, default=0, help="allowed errors per thousand requests (default 0)")
    parser.add_argument("--max-p95-ms", type=int, default=1000, help="p95 latency ceiling in ms (default 1000)")
    parser.add_argument("--min-rps", type=int, default=1, help="minimum requests per second (default 1)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args(argv)
    try:
        if min(args.max_error_permille, args.max_p95_ms, args.min_rps) < 0:
            raise ValueError("budgets must not be negative")
        result = evaluate(load_scenarios(Path(args.report)), args.max_error_permille, args.max_p95_ms, args.min_rps)
    except ValueError as exc:
        print(f"load-check: UNABLE TO VERIFY ({exc})", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"load-check: {result['scenarios']} scenarios, {len(result['breaches'])} over budget")
        for sid, found in result["breaches"].items():
            print(f"  BREACH {sid} {','.join(found)}")
    return 1 if result["breaches"] else 0


if __name__ == "__main__":
    sys.exit(main())
