#!/usr/bin/env python3
"""Deterministic, read-only guided-app check (OC-P1-02 slice 1, #473).

Evidence manifest: ``{"revision": 40-hex, "evidence": [{"screen", "viewport",
"state", "keyboard_ok": bool, "a11y_serious": int >= 0, "completion_claimed":
bool, "completion_evidence_sha256": 64-hex or null}]}``.
Every required screen must be evidenced at every required viewport and state,
be keyboard operable, have no serious/critical accessibility violations, and
never claim completion without an evidence digest. No network, no writes,
no clock.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")
SCREENS = ("welcome", "discovery", "brief", "team", "build", "quality", "preview", "mission-control")
VIEWPORTS = (320, 390, 768, 1024, 1440)
STATES = ("ready", "empty", "error", "slow")


def load(path: Path) -> dict[tuple, dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"manifest unreadable: {path.name} ({exc.__class__.__name__})") from exc
    if not isinstance(data, dict):
        raise ValueError("manifest is not an object")
    rev = data.get("revision")
    if not isinstance(rev, str) or not HEX40.fullmatch(rev):
        raise ValueError("manifest needs a 40-hex revision")
    items = data.get("evidence")
    if not isinstance(items, list) or not items:
        raise ValueError("manifest has no non-empty evidence list")
    out: dict[tuple, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("evidence entry is not an object")
        screen, vp, state = item.get("screen"), item.get("viewport"), item.get("state")
        if not isinstance(screen, str) or not isinstance(state, str) or isinstance(vp, bool) or not isinstance(vp, int):
            raise ValueError("evidence entry needs string screen/state and integer viewport")
        for flag in ("keyboard_ok", "completion_claimed"):
            if not isinstance(item.get(flag), bool):
                raise ValueError(f"{screen} {vp} {state}: {flag} must be a boolean")
        serious = item.get("a11y_serious")
        if isinstance(serious, bool) or not isinstance(serious, int) or serious < 0:
            raise ValueError(f"{screen} {vp} {state}: a11y_serious must be a non-negative integer")
        digest = item.get("completion_evidence_sha256")
        if digest is not None and not isinstance(digest, str):
            raise ValueError(f"{screen} {vp} {state}: completion_evidence_sha256 must be a string or null")
        key = (screen, vp, state)
        if key in out:
            raise ValueError(f"duplicate evidence entry {screen} {vp} {state}")
        out[key] = item
    return out


def evaluate(entries: dict[tuple, dict]) -> dict:
    fmt = lambda k: f"{k[0]} {k[1]} {k[2]}"  # noqa: E731
    required = {(s, v, t) for s in SCREENS for v in VIEWPORTS for t in STATES}
    return {
        "entries": len(entries),
        "missing": [fmt(k) for k in sorted(required - set(entries))],
        "unexpected": [fmt(k) for k in sorted(set(entries) - required)],
        "keyboard": [fmt(k) for k in sorted(entries) if not entries[k]["keyboard_ok"]],
        "a11y": [fmt(k) for k in sorted(entries) if entries[k]["a11y_serious"] > 0],
        "fictional_completion": [
            fmt(k) for k in sorted(entries)
            if entries[k]["completion_claimed"]
            and not (isinstance(entries[k].get("completion_evidence_sha256"), str)
                     and HEX64.fullmatch(entries[k]["completion_evidence_sha256"]))],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only guided-app evidence check.")
    parser.add_argument("evidence", help="evidence manifest JSON file")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args(argv)
    try:
        result = evaluate(load(Path(args.evidence)))
    except ValueError as exc:
        print(f"app-check: UNABLE TO VERIFY ({exc})", file=sys.stderr)
        return 2
    labels = (("missing", "MISSING"), ("unexpected", "UNEXPECTED"), ("keyboard", "KEYBOARD"),
              ("a11y", "A11Y"), ("fictional_completion", "FICTIONAL_COMPLETION"))
    failed = any(result[k] for k, _ in labels)
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"app-check: {result['entries']} entries, " +
              ", ".join(f"{len(result[k])} {k.replace('_', ' ')}" for k, _ in labels))
        for key, label in labels:
            for item in result[key]:
                print(f"  {label} {item}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
