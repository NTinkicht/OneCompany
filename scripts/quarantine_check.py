#!/usr/bin/env python3
"""Deterministic, read-only quarantine registry check (OC-P1-04 slice 4, #441).

Inputs: a quarantine file ``{"quarantined": [{"test", "issue", "reason"}]}`` and a run file
``{"results": {"<test id>": "pass|fail|error|skip"}}``. Quarantine without bypass: a skipped test
must be registered, a registered test is never counted as a pass, and a registry entry whose test
passes (stale) or is absent from the run (missing) is reported. No network, no writes, no clock.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from flaky_report import load_run  # noqa: E402


def load_quarantine(path: Path) -> list[dict]:
    """Return validated quarantine entries; raise ValueError on anything malformed."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"quarantine file unreadable: {path.name} ({exc.__class__.__name__})") from exc
    items = data.get("quarantined") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ValueError(f"quarantine file has no quarantined list: {path.name}")
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("quarantine entry is not an object")
        for key in ("test", "issue", "reason"):
            value = item.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"quarantine entry needs a non-empty string {key}")
        if item["test"] in seen:
            raise ValueError(f"duplicate quarantined test: {item['test']}")
        seen.add(item["test"])
    return items


def classify(entries: list[dict], run: dict[str, str]) -> dict:
    registered = {e["test"] for e in entries}
    out = {"quarantined": [], "stale_entry": [], "missing": [], "unregistered_skip": []}
    for test in sorted(registered):
        outcome = run.get(test)
        if outcome is None:
            out["missing"].append(test)
        elif outcome == "pass":
            out["stale_entry"].append(test)
        else:
            out["quarantined"].append(test)
    out["unregistered_skip"] = sorted(t for t, o in run.items() if o == "skip" and t not in registered)
    return out


def exit_code(result: dict) -> int:
    return 1 if result["stale_entry"] or result["missing"] or result["unregistered_skip"] else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only quarantine registry check.")
    parser.add_argument("quarantine", help="quarantine JSON file")
    parser.add_argument("run", help="run JSON file")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args(argv)
    try:
        result = classify(load_quarantine(Path(args.quarantine)), load_run(Path(args.run)))
    except ValueError as exc:
        print(f"quarantine-check: UNABLE TO VERIFY ({exc})", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"quarantine-check: {len(result['quarantined'])} quarantined (never counted as passes)")
        for key, label in (("unregistered_skip", "UNREGISTERED_SKIP"), ("stale_entry", "STALE_ENTRY"), ("missing", "MISSING")):
            for name in result[key]:
                print(f"  {label} {name}")
    return exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
