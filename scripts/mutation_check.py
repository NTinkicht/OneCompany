#!/usr/bin/env python3
"""Deterministic, read-only mutation-result check (OC-P1-04 slice 6, #445).

Input: ``{"revision": 40-hex, "mutants": [{"id", "file", "status", "justification"?}]}`` where status
is killed, timeout, survived, no_coverage or equivalent. Survived and uncovered mutants fail, an
equivalent waiver needs a justification, and the score (killed+timeout over non-equivalent) must meet
``--min-score``. No network, no writes, no clock.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HEX40 = re.compile(r"[0-9a-f]{40}")
STATUSES = {"killed", "timeout", "survived", "no_coverage", "equivalent"}


def load_mutants(path: Path) -> list[dict]:
    """Return validated mutants; raise ValueError on anything malformed."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"report unreadable: {path.name} ({exc.__class__.__name__})") from exc
    if not isinstance(data, dict):
        raise ValueError("report is not an object")
    revision = data.get("revision")
    if not isinstance(revision, str) or not HEX40.fullmatch(revision):
        raise ValueError("report needs a 40-hex revision")
    items = data.get("mutants")
    if not isinstance(items, list) or not items:
        raise ValueError("report has no non-empty mutants list")
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("mutant is not an object")
        mid = item.get("id")
        if not isinstance(mid, str) or not mid.strip():
            raise ValueError("mutant needs a non-empty string id")
        if mid in seen:
            raise ValueError(f"duplicate mutant id: {mid}")
        seen.add(mid)
        if not isinstance(item.get("file"), str) or not item["file"].strip():
            raise ValueError(f"{mid} needs a non-empty string file")
        if item.get("status") not in STATUSES:
            raise ValueError(f"{mid} has an unknown status")
        just = item.get("justification")
        if just is not None and not isinstance(just, str):
            raise ValueError(f"{mid} justification must be a string")
    return items


def classify(mutants: list[dict]) -> dict:
    out = {"survived": [], "uncovered": [], "unjustified_equivalent": [], "score": None}
    detected = 0
    countable = 0
    for m in sorted(mutants, key=lambda x: x["id"]):
        status = m["status"]
        if status == "equivalent":
            if not (m.get("justification") or "").strip():
                out["unjustified_equivalent"].append(m["id"])
            continue
        countable += 1
        if status in ("killed", "timeout"):
            detected += 1
        elif status == "survived":
            out["survived"].append(m["id"])
        else:
            out["uncovered"].append(m["id"])
    if countable:
        out["score"] = detected * 100 // countable
    return out


def exit_code(result: dict, min_score: int) -> int:
    if result["score"] is None:
        return 2
    failed = result["survived"] or result["uncovered"] or result["unjustified_equivalent"]
    return 1 if failed or result["score"] < min_score else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only mutation-result check.")
    parser.add_argument("report", help="mutation report JSON file")
    parser.add_argument("--min-score", type=int, default=100, help="minimum percent score (0-100, default 100)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args(argv)
    try:
        if not 0 <= args.min_score <= 100:
            raise ValueError("--min-score must be 0-100")
        result = classify(load_mutants(Path(args.report)))
        if result["score"] is None:
            raise ValueError("every mutant is equivalent so the score is undefined")
    except ValueError as exc:
        print(f"mutation-check: UNABLE TO VERIFY ({exc})", file=sys.stderr)
        return 2
    code = exit_code(result, args.min_score)
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"mutation-check: score {result['score']}% (minimum {args.min_score}%)")
        for key, label in (("survived", "SURVIVED"), ("uncovered", "UNCOVERED"), ("unjustified_equivalent", "UNJUSTIFIED_EQUIVALENT")):
            for name in result[key]:
                print(f"  {label} {name}")
    return code


if __name__ == "__main__":
    sys.exit(main())
