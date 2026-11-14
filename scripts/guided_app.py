#!/usr/bin/env python3
"""Static guided-app renderer (OC-P1-02 slice 2, #477).

Renders the eight guided screens (Welcome -> Mission Control) as one no-JS HTML
page styled from ``.onecompany/ui/design-tokens.json``. Honest by construction:
the default state of every screen is "empty" and no state ever says complete.
Stdlib only; no network, no clock; writes only to an explicit ``--out`` file.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOKENS = ROOT / ".onecompany" / "ui" / "design-tokens.json"
SCREENS = (
    ("welcome", "Welcome", "Start a new product or adopt an existing repository.", "start"),
    ("discovery", "Discovery", "Read-only analysis of stack, tests and permissions.", "onboard"),
    ("brief", "Brief", "Edit the Product Brief; approval is always explicit.", "brief"),
    ("team", "Team", "Proposed role-to-model assignments; all start unqualified.", "team"),
    ("build", "Build", "Bounded work units, one branch and one pull request each.", "journey"),
    ("quality", "Quality", "Acceptance criteria mapped to test evidence.", "ac-coverage"),
    ("preview", "Preview", "Local preview of the running application.", "preview-local"),
    ("mission-control", "Mission Control", "Read-only status of work, blockers and next action.", "mission-control"),
)
STATES = {
    "ready": ("Ready", "Inputs for this step are available. Run the command to continue."),
    "empty": ("Not started", "Nothing here yet. Run the command below to begin."),
    "error": ("Error", "This step could not be read. Fix the reported problem, then run the command again."),
    "slow": ("Loading", "This step is taking longer than usual. It has not finished."),
}
COLORS = {  # token pair name -> (foreground var, background var or None)
    "text-on-surface": ("--fg", "--bg"), "muted-on-surface": ("--muted", None),
    "action-label": ("--action-fg", "--action-bg"), "border-on-surface": ("--border", None),
    "focus-ring": ("--focus", None),
}
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def theme_vars(data: object, theme: str) -> str:
    try:
        pairs = data["themes"][theme]["pairs"]  # type: ignore[index]
        by_name = {p["name"]: p for p in pairs}
        out = []
        for name, (fg, bg) in COLORS.items():
            pair = by_name[name]
            for var, key in ((fg, "fg"), (bg, "bg")):
                if var is None:
                    continue
                if not isinstance(pair[key], str) or not HEX.match(pair[key]):
                    raise ValueError("bad colour")
                out.append(f"{var}:{pair[key]}")
        return ";".join(out)
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"design tokens: theme {theme!r} is malformed") from None


def render(statuses: dict[str, str] | None = None, tokens: object | None = None, rtl: bool = False) -> str:
    statuses = statuses or {}
    for key, value in statuses.items():
        if key not in {s[0] for s in SCREENS} or value not in STATES:
            raise ValueError(f"unknown screen or state: {key!r}={value!r}")
    data = tokens if tokens is not None else json.loads(TOKENS.read_text(encoding="utf-8"))
    target = data.get("min_target_px") if isinstance(data, dict) else None
    if isinstance(target, bool) or not isinstance(target, int) or target < 24:
        raise ValueError("design tokens: min_target_px must be an integer >= 24")
    light, dark = theme_vars(data, "light"), theme_vars(data, "dark")
    nav = "".join(f'<li><a href="#{k}">{html.escape(t)}</a></li>' for k, t, _, _ in SCREENS)
    sections = []
    for key, title, blurb, cmd in SCREENS:
        label, note = STATES[statuses.get(key, "empty")]
        sections.append(
            f'<section id="{key}" aria-labelledby="h-{key}"><h2 id="h-{key}">{html.escape(title)}</h2>'
            f'<p class="state" data-state="{statuses.get(key, "empty")}">Status: <strong>{label}</strong></p>'
            f'<p>{html.escape(blurb)}</p><p>{note}</p>'
            f'<p>Command: <code>python onecompany.py {cmd}</code></p></section>')
    css = (
        f":root{{{light};color-scheme:light dark}}"
        f"@media (prefers-color-scheme:dark){{:root{{{dark}}}}}"
        "*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);"
        "font:16px/1.5 system-ui,sans-serif}"
        ".skip{position:absolute;inset-inline-start:-999px}.skip:focus{inset-inline-start:8px;top:8px}"
        f"a{{color:var(--action-bg);display:inline-block;min-height:{target}px;min-width:{target}px;padding:8px 12px}}"
        "a:focus-visible{outline:3px solid var(--focus);outline-offset:2px}"
        "header,main{padding-inline:16px;max-width:72rem;margin-inline:auto}"
        "nav ul{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:4px}"
        "section{border:1px solid var(--border);border-radius:8px;padding:16px;margin-block:16px;"
        "overflow-wrap:anywhere}.state{color:var(--muted)}.state strong{color:var(--fg)}"
        "@media (min-width:768px){main{display:grid;grid-template-columns:1fr 1fr;gap:16px}"
        "section{margin:0}}@media (min-width:1024px){main{grid-template-columns:repeat(3,1fr)}}")
    return (
        f'<!doctype html><html lang="en" dir="{"rtl" if rtl else "ltr"}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">'
        f"<title>OneCompany guided setup</title><style>{css}</style></head><body>"
        '<a class="skip" href="#main">Skip to content</a>'
        f'<header><h1>OneCompany guided setup</h1><nav aria-label="Steps"><ul>{nav}</ul></nav></header>'
        f'<main id="main">{"".join(sections)}</main></body></html>\n')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Render the static guided application.")
    parser.add_argument("--status", help='JSON file mapping screen -> ready|empty|error|slow')
    parser.add_argument("--out", help="write HTML to this file instead of stdout")
    parser.add_argument("--rtl", action="store_true")
    args = parser.parse_args(argv)
    try:
        statuses = json.loads(Path(args.status).read_text(encoding="utf-8")) if args.status else {}
        if not isinstance(statuses, dict):
            raise ValueError("status file must be a JSON object")
        page = render(statuses, rtl=args.rtl)
        if args.out:
            out = Path(args.out)
            if out.is_symlink():
                raise ValueError("refusing to write through a symlink")
            out.write_text(page, encoding="utf-8")
        else:
            sys.stdout.write(page)
    except (OSError, ValueError) as exc:
        print(f"guided-app: UNABLE TO RENDER ({exc})", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
