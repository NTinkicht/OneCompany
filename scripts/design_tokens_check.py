#!/usr/bin/env python3
"""Read-only design-token gate (OC-P1-01 slice 1).

Computes WCAG 2.x contrast for every declared colour pair in every theme and
checks structural invariants. Fails closed on anything malformed. Stdlib only;
no network, no writes, no clock.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / ".onecompany" / "ui" / "design-tokens.json"
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
MIN_RATIO = {"text": 4.5, "ui": 3.0, "focus": 3.0}
REQUIRED_THEMES = ("light", "dark")
ABSOLUTE_MIN_TARGET = 24


def _channel(value: int) -> float:
    c = value / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def luminance(color: str) -> float:
    if not isinstance(color, str) or not HEX.match(color):
        raise ValueError("malformed hex colour")
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(fg: str, bg: str) -> float:
    hi, lo = sorted((luminance(fg), luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def check_tokens(data: object) -> tuple[list[dict], list[str]]:
    """Return (pair results, problems). Any problem means the gate fails."""
    problems: list[str] = []
    results: list[dict] = []
    if not isinstance(data, dict):
        return results, ["tokens: root must be an object"]
    target = data.get("min_target_px")
    if isinstance(target, bool) or not isinstance(target, (int, float)) or not math.isfinite(target) \
            or target < ABSOLUTE_MIN_TARGET:
        problems.append(f"min_target_px: must be a finite number >= {ABSOLUTE_MIN_TARGET}")
    dirs = data.get("dir_support")
    if not isinstance(dirs, list) or not {"ltr", "rtl"} <= set(map(str, dirs)):
        problems.append("dir_support: must list ltr and rtl")
    spacing = data.get("spacing_px")
    if not isinstance(spacing, list) or not spacing \
            or any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in spacing) \
            or spacing[0] != 0 or any(a >= b for a, b in zip(spacing, spacing[1:])):
        problems.append("spacing_px: must be a strictly ascending list of non-negative integers starting at 0")
    themes = data.get("themes")
    if not isinstance(themes, dict):
        return results, problems + ["themes: must be an object"]
    names_by_theme: dict[str, set[str]] = {}
    for theme in REQUIRED_THEMES:
        if theme not in themes:
            problems.append(f"themes.{theme}: missing")
    for theme in sorted(themes):
        pairs = themes[theme].get("pairs") if isinstance(themes[theme], dict) else None
        if not isinstance(pairs, list) or not pairs:
            problems.append(f"themes.{theme}.pairs: must be a non-empty list")
            continue
        kinds = set()
        seen: set[str] = set()
        for pair in pairs:
            name = pair.get("name") if isinstance(pair, dict) else None
            label = f"{theme}/{name}"
            kind = pair.get("kind") if isinstance(pair, dict) else None
            if kind not in MIN_RATIO or not isinstance(name, str) or not name:
                problems.append(f"{label}: unknown kind or missing name")
                continue
            if name in seen:
                problems.append(f"{label}: duplicate pair name")
                continue
            seen.add(name)
            kinds.add(kind)
            try:
                ratio = contrast(pair.get("fg"), pair.get("bg"))
            except ValueError:
                problems.append(f"{label}: malformed hex colour")
                continue
            ok = ratio >= MIN_RATIO[kind]
            results.append({"theme": theme, "name": name, "kind": kind, "ratio": round(ratio, 2),
                            "required": MIN_RATIO[kind], "ok": ok})
            if not ok:
                problems.append(f"{label}: contrast {ratio:.2f} < {MIN_RATIO[kind]}")
        names_by_theme[theme] = seen
        if "focus" not in kinds:
            problems.append(f"themes.{theme}: missing focus-ring pair")
    all_names = set().union(*names_by_theme.values()) if names_by_theme else set()
    for theme in sorted(names_by_theme):
        for missing in sorted(all_names - names_by_theme[theme]):
            problems.append(f"themes.{theme}: missing pair {missing} declared in another theme")
    return results, problems


def _reject_duplicate_keys(pairs):
    """``object_pairs_hook``: json keeps the last repeated key, which could hide a finding or a revision; refuse it."""
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate key")
    return dict(pairs)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only design-token contrast gate.")
    parser.add_argument("--tokens", default=str(DEFAULT), help="token JSON file")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)
    try:
        data = json.loads(Path(args.tokens).read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (OSError, ValueError):
        print("design-tokens-check: cannot read tokens", file=sys.stderr)
        return 2
    results, problems = check_tokens(data)
    if args.json:
        print(json.dumps({"ok": not problems, "pairs": results, "problems": problems}, indent=2, sort_keys=True))
    else:
        for r in results:
            print(f"{r['theme']}/{r['name']}: {r['ratio']}:1 (>= {r['required']}) {'ok' if r['ok'] else 'FAIL'}")
        for p in problems:
            print(f"PROBLEM {p}")
        print("design-tokens: " + ("ok" if not problems else f"FAILED ({len(problems)})"))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
