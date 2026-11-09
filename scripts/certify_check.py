#!/usr/bin/env python3
"""Deterministic, read-only end-to-end certification check (OC-P1-13 slice 1, #475).

Manifest: ``{"revision": 40-hex, "certifier": str, "authors": [str],
"scenarios": [{"id", "result": "pass"|"fail", "evidence_sha256": 64-hex,
"revision": 40-hex, "error_rate": 0..1, "p95_ms": >= 0, "ac_ids": [str]}]}``.
Every fixed scenario must pass on the certified revision with an evidence
digest, inside the error and latency budgets, traced to acceptance criteria,
and the certifier must not be an author. Verdict is GO only when nothing
failed. No network, no writes, no clock.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")
SCENARIOS = ("create-fresh", "adopt-existing", "portfolio-two-app", "failure-ci-red",
             "failure-reviewer-outage", "failure-budget-exhausted", "failure-stale-head")
MAX_ERROR_RATE = 0.01
MAX_P95_MS = 2000


def _num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"manifest unreadable: {path.name} ({exc.__class__.__name__})") from exc
    if not isinstance(data, dict):
        raise ValueError("manifest is not an object")
    if not isinstance(data.get("revision"), str) or not HEX40.fullmatch(data["revision"]):
        raise ValueError("manifest needs a 40-hex revision")
    if not isinstance(data.get("certifier"), str) or not data["certifier"].strip():
        raise ValueError("manifest needs a certifier")
    authors = data.get("authors")
    if not isinstance(authors, list) or not all(isinstance(a, str) for a in authors):
        raise ValueError("authors must be a list of strings")
    items = data.get("scenarios")
    if not isinstance(items, list) or not items:
        raise ValueError("manifest has no non-empty scenarios list")
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ValueError("scenario entry needs a string id")
        sid = item["id"]
        if sid in seen:
            raise ValueError(f"duplicate scenario {sid}")
        seen.add(sid)
        if item.get("result") not in ("pass", "fail"):
            raise ValueError(f"{sid}: result must be pass or fail")
        for key in ("evidence_sha256", "revision"):
            if not isinstance(item.get(key), str):
                raise ValueError(f"{sid}: {key} must be a string")
        if not _num(item.get("error_rate")) or not 0 <= item["error_rate"] <= 1:
            raise ValueError(f"{sid}: error_rate must be a number in 0..1")
        if not _num(item.get("p95_ms")) or item["p95_ms"] < 0:
            raise ValueError(f"{sid}: p95_ms must be a non-negative number")
        acs = item.get("ac_ids")
        if not isinstance(acs, list) or not all(isinstance(a, str) and a.strip() for a in acs):
            raise ValueError(f"{sid}: ac_ids must be a list of non-blank strings")
    return data


def evaluate(data: dict) -> dict:
    by_id = {s["id"]: s for s in data["scenarios"]}
    ids = set(by_id)
    out = {
        "scenarios": len(by_id),
        "missing": sorted(set(SCENARIOS) - ids),
        "unexpected": sorted(ids - set(SCENARIOS)),
        "failed": sorted(i for i, s in by_id.items() if s["result"] != "pass"),
        "evidence": sorted(i for i, s in by_id.items() if not HEX64.fullmatch(s["evidence_sha256"])),
        "stale_revision": sorted(i for i, s in by_id.items() if s["revision"] != data["revision"]),
        "error_budget": sorted(i for i, s in by_id.items() if s["error_rate"] > MAX_ERROR_RATE),
        "latency_budget": sorted(i for i, s in by_id.items() if s["p95_ms"] > MAX_P95_MS),
        "untraced": sorted(i for i, s in by_id.items() if not s["ac_ids"]),
        "independence": [data["certifier"]] if data["certifier"].strip().lower() in
                        {a.strip().lower() for a in data["authors"]} else [],
    }
    out["verdict"] = "GO" if not any(out[k] for k in LABELS) else "NO-GO"
    return out


LABELS = ("missing", "unexpected", "failed", "evidence", "stale_revision", "error_budget",
          "latency_budget", "untraced", "independence")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only end-to-end certification go/no-go check.")
    parser.add_argument("manifest", help="certification manifest JSON file")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args(argv)
    try:
        result = evaluate(load(Path(args.manifest)))
    except ValueError as exc:
        print(f"certify-check: UNABLE TO VERIFY ({exc})", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"certify-check: {result['verdict']} ({result['scenarios']} scenarios)")
        for key in LABELS:
            for item in result[key]:
                print(f"  {key.upper()} {item}")
    return 0 if result["verdict"] == "GO" else 1


if __name__ == "__main__":
    sys.exit(main())
