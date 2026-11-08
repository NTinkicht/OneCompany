#!/usr/bin/env python3
"""Deterministic, read-only running-app fixture check (OC-P1-04 slice 5, #443).

Input: ``{"fixtures": [{"id", "kind", "revision", "command", "probe": {"method", "path",
"status", "response_sha256"}}]}``. Only ``kind == "running-app"`` is genuine; mock, stub, recorded
or in-process fixtures are reported, copied probe evidence is reported, and a 5xx probe is
unhealthy. No network, no writes, no clock.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")


def _text(obj: dict, key: str, where: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where} needs a non-empty string {key}")
    return value


def load_fixtures(path: Path) -> list[dict]:
    """Return validated fixtures; raise ValueError on anything malformed."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"fixtures file unreadable: {path.name} ({exc.__class__.__name__})") from exc
    items = data.get("fixtures") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise ValueError(f"fixtures file has no non-empty fixtures list: {path.name}")
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("fixture is not an object")
        fid = _text(item, "id", "fixture")
        if fid in seen:
            raise ValueError(f"duplicate fixture id: {fid}")
        seen.add(fid)
        _text(item, "kind", fid)
        _text(item, "command", fid)
        revision = item.get("revision")
        if not isinstance(revision, str) or not HEX40.fullmatch(revision):
            raise ValueError(f"{fid} needs a 40-hex revision")
        probe = item.get("probe")
        if not isinstance(probe, dict):
            raise ValueError(f"{fid} needs a probe object")
        _text(probe, "method", f"{fid} probe")
        if not _text(probe, "path", f"{fid} probe").startswith("/"):
            raise ValueError(f"{fid} probe path must start with /")
        status = probe.get("status")
        if isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599:
            raise ValueError(f"{fid} probe needs an integer status 100-599")
        digest = probe.get("response_sha256")
        if not isinstance(digest, str) or not HEX64.fullmatch(digest):
            raise ValueError(f"{fid} probe needs a 64-hex response_sha256")
    return items


def classify(fixtures: list[dict]) -> dict:
    out = {"genuine": [], "not_genuine": [], "unhealthy": [], "duplicate_evidence": []}
    by_hash: dict[str, list[str]] = {}
    for fx in fixtures:
        by_hash.setdefault(fx["probe"]["response_sha256"], []).append(fx["id"])
    for fx in sorted(fixtures, key=lambda f: f["id"]):
        if fx["kind"] != "running-app":
            out["not_genuine"].append(fx["id"])
        elif fx["probe"]["status"] >= 500:
            out["unhealthy"].append(fx["id"])
        elif len(by_hash[fx["probe"]["response_sha256"]]) > 1:
            out["duplicate_evidence"].append(fx["id"])
        else:
            out["genuine"].append(fx["id"])
    return out


def exit_code(result: dict) -> int:
    return 1 if result["not_genuine"] or result["unhealthy"] or result["duplicate_evidence"] else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only running-app fixture check.")
    parser.add_argument("fixtures", help="fixtures JSON file")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args(argv)
    try:
        result = classify(load_fixtures(Path(args.fixtures)))
    except ValueError as exc:
        print(f"fixture-check: UNABLE TO VERIFY ({exc})", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"fixture-check: {len(result['genuine'])} genuine running-app fixture(s)")
        for key, label in (("not_genuine", "NOT_GENUINE"), ("unhealthy", "UNHEALTHY"), ("duplicate_evidence", "DUPLICATE_EVIDENCE")):
            for name in result[key]:
                print(f"  {label} {name}")
    return exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
