#!/usr/bin/env python3
"""Deterministic, read-only visual-golden check (OC-P1-01 slice 2, #455).

Golden manifest: ``{"revision": 40-hex, "viewports": [px], "themes": [str],
"goldens": [{"id", "viewport", "theme", "sha256"}]}``.
Capture manifest: ``{"revision": 40-hex, "captures": [same entry shape]}``.
Every id must be golden for every declared viewport and theme, and every golden
must be captured with an identical digest. No network, no writes, no clock.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HEX40 = re.compile(r"[0-9a-f]{40}")
HEX64 = re.compile(r"[0-9a-f]{64}")


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"manifest unreadable: {path.name} ({exc.__class__.__name__})") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} is not an object")
    rev = data.get("revision")
    if not isinstance(rev, str) or not HEX40.fullmatch(rev):
        raise ValueError(f"{path.name} needs a 40-hex revision")
    return data


def _entries(data: dict, key: str, name: str, viewports: set[int], themes: set[str]) -> dict[tuple, str]:
    items = data.get(key)
    if not isinstance(items, list) or not items:
        raise ValueError(f"{name} has no non-empty {key} list")
    out: dict[tuple, str] = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError(f"{name} entry is not an object")
        eid, vp, theme, digest = (item.get(k) for k in ("id", "viewport", "theme", "sha256"))
        if not isinstance(eid, str) or not eid.strip():
            raise ValueError(f"{name} entry needs a non-empty string id")
        if isinstance(vp, bool) or not isinstance(vp, int) or vp not in viewports:
            raise ValueError(f"{name} {eid} has an undeclared viewport")
        if not isinstance(theme, str) or theme not in themes:
            raise ValueError(f"{name} {eid} has an undeclared theme")
        if not isinstance(digest, str) or not HEX64.fullmatch(digest):
            raise ValueError(f"{name} {eid} needs a 64-hex sha256")
        key_t = (eid, vp, theme)
        if key_t in out:
            raise ValueError(f"{name} has duplicate entry {eid} {vp} {theme}")
        out[key_t] = digest
    return out


def load(golden_path: Path, capture_path: Path) -> tuple[dict, dict, list[int], list[str]]:
    golden, capture = _load(golden_path), _load(capture_path)
    vps, themes = golden.get("viewports"), golden.get("themes")
    if (not isinstance(vps, list) or not vps or any(isinstance(v, bool) or not isinstance(v, int) or v < 1 for v in vps)
            or len(set(vps)) != len(vps)):
        raise ValueError("golden viewports must be a non-empty list of unique positive integers")
    if not isinstance(themes, list) or not themes or any(not isinstance(t, str) or not t.strip() for t in themes) \
            or len(set(themes)) != len(themes):
        raise ValueError("golden themes must be a non-empty list of unique strings")
    g = _entries(golden, "goldens", "golden", set(vps), set(themes))
    c = _entries(capture, "captures", "capture", set(vps), set(themes))
    return g, c, sorted(vps), sorted(themes)


def evaluate(g: dict, c: dict, vps: list[int], themes: list[str]) -> dict:
    ids = sorted({k[0] for k in g})
    incomplete = [f"{i} {v} {t}" for i in ids for v in vps for t in themes if (i, v, t) not in g]
    fmt = lambda k: f"{k[0]} {k[1]} {k[2]}"  # noqa: E731
    return {
        "goldens": len(g),
        "incomplete_matrix": incomplete,
        "missing": [fmt(k) for k in sorted(g) if k not in c],
        "changed": [fmt(k) for k in sorted(g) if k in c and c[k] != g[k]],
        "unexpected": [fmt(k) for k in sorted(c) if k not in g],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only visual-golden check.")
    parser.add_argument("golden", help="golden manifest JSON file")
    parser.add_argument("capture", help="capture manifest JSON file")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args(argv)
    try:
        result = evaluate(*load(Path(args.golden), Path(args.capture)))
    except ValueError as exc:
        print(f"visual-golden-check: UNABLE TO VERIFY ({exc})", file=sys.stderr)
        return 2
    labels = (("incomplete_matrix", "INCOMPLETE_MATRIX"), ("missing", "MISSING"),
              ("changed", "CHANGED"), ("unexpected", "UNEXPECTED"))
    failed = any(result[k] for k, _ in labels)
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"visual-golden-check: {result['goldens']} goldens, " +
              ", ".join(f"{len(result[k])} {k.replace('_', ' ')}" for k, _ in labels))
        for key, label in labels:
            for item in result[key]:
                print(f"  {label} {item}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
