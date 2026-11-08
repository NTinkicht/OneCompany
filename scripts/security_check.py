#!/usr/bin/env python3
"""Deterministic, read-only security-scan check (OC-P1-04 slice 9, #451).

Input: ``{"revision": 40-hex, "targets": [{"id", "findings": [{"id", "severity", "kind"}], "waived": [finding id]}]}``.
Unwaived high/critical findings fail; ``secret`` findings always fail and cannot be waived;
waivers that match no finding fail. low/medium are warnings. No network, no writes, no clock.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HEX40 = re.compile(r"[0-9a-f]{40}")
SEVERITIES = {"low", "medium", "high", "critical"}
KINDS = {"sast", "dependency", "secret"}
BLOCKING = {"high", "critical"}


def _name(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def load_targets(path: Path) -> list[dict]:
    """Return validated targets; raise ValueError on anything malformed."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"report unreadable: {path.name} ({exc.__class__.__name__})") from exc
    if not isinstance(data, dict):
        raise ValueError("report is not an object")
    revision = data.get("revision")
    if not isinstance(revision, str) or not HEX40.fullmatch(revision):
        raise ValueError("report needs a 40-hex revision")
    targets = data.get("targets")
    if not isinstance(targets, list) or not targets:
        raise ValueError("report has no non-empty targets list")
    seen: set[str] = set()
    for target in targets:
        if not isinstance(target, dict):
            raise ValueError("target is not an object")
        tid = target.get("id")
        if not _name(tid):
            raise ValueError("target needs a non-empty string id")
        if tid in seen:
            raise ValueError(f"duplicate target id: {tid}")
        seen.add(tid)
        findings = target.get("findings")
        waived = target.get("waived", [])
        if not isinstance(findings, list) or not isinstance(waived, list):
            raise ValueError(f"{tid} findings and waived must be lists")
        ids: set[str] = set()
        for f in findings:
            if not isinstance(f, dict):
                raise ValueError(f"{tid} finding is not an object")
            if not _name(f.get("id")):
                raise ValueError(f"{tid} finding needs a non-empty string id")
            if f["id"] in ids:
                raise ValueError(f"{tid} duplicate finding id: {f['id']}")
            ids.add(f["id"])
            if not isinstance(f.get("severity"), str) or f["severity"] not in SEVERITIES:
                raise ValueError(f"{tid} finding has unknown severity")
            if not isinstance(f.get("kind"), str) or f["kind"] not in KINDS:
                raise ValueError(f"{tid} finding has unknown kind")
        for wid in waived:
            if not _name(wid):
                raise ValueError(f"{tid} waived entries must be non-empty strings")
    return targets


def evaluate(targets: list[dict]) -> dict:
    blocking: list[str] = []
    unwaivable: list[str] = []
    warnings: list[str] = []
    stale: list[str] = []
    for target in sorted(targets, key=lambda t: t["id"]):
        tid = target["id"]
        waived = set(target.get("waived", []))
        present = {f["id"] for f in target["findings"]}
        for f in sorted(target["findings"], key=lambda x: x["id"]):
            if f["kind"] == "secret":
                blocking.append(f"{tid} {f['id']}")
                if f["id"] in waived:
                    unwaivable.append(f"{tid} {f['id']}")
            elif f["severity"] in BLOCKING:
                if f["id"] not in waived:
                    blocking.append(f"{tid} {f['id']}")
            else:
                warnings.append(f"{tid} {f['id']}")
        stale.extend(f"{tid} {wid}" for wid in sorted(waived - present))
    return {"targets": len(targets), "blocking": blocking, "unwaivable": unwaivable,
            "warnings": warnings, "stale_waivers": stale}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only security-scan check.")
    parser.add_argument("report", help="security report JSON file")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args(argv)
    try:
        result = evaluate(load_targets(Path(args.report)))
    except ValueError as exc:
        print(f"security-check: UNABLE TO VERIFY ({exc})", file=sys.stderr)
        return 2
    failed = bool(result["blocking"] or result["stale_waivers"])
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"security-check: {result['targets']} targets, {len(result['blocking'])} blocking, "
              f"{len(result['warnings'])} warnings, {len(result['stale_waivers'])} stale waivers")
        for item in result["blocking"]:
            print(f"  BLOCKING {item}")
        for item in result["unwaivable"]:
            print(f"  UNWAIVABLE {item}")
        for item in result["stale_waivers"]:
            print(f"  STALE_WAIVER {item}")
        for item in result["warnings"]:
            print(f"  WARN {item}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
