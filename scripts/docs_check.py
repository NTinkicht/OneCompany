#!/usr/bin/env python3
"""Deterministic, read-only documentation check (OC-P1-12 slice 1, #471).

Reports (a) required docs that are missing, (b) relative markdown links that do
not resolve inside the repository, and (c) ``onecompany.py`` commands that no
README/docs page documents as ``onecompany.py <command>``. No network, no writes.
Exit 0 clean, 1 findings, 2 unable to verify.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REQUIRED = (
    "README.md", "docs/ONBOARDING.md", "docs/15-MINUTE-QUICKSTART.md", "docs/SETUP-FROM-ZERO.md",
    "docs/MIGRATION.md", "docs/UPGRADING.md", "docs/TROUBLESHOOTING.md", "docs/FAQ.md",
    "docs/INSTALL-SKILL.md", "docs/RELEASE-CHECKLIST.md",
)
LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
KEY = re.compile(r'"([a-z0-9][a-z0-9-]*)"\s*:\s*\[')


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f"unreadable: {path.name} ({exc.__class__.__name__})") from exc


def commands(root: Path) -> list[str]:
    src = _read(root / "onecompany.py")
    if "COMMANDS = {" not in src:
        raise ValueError("onecompany.py has no COMMANDS registry")
    body = src.split("COMMANDS = {", 1)[1].split("\n}\n", 1)[0]
    found = sorted(set(KEY.findall(body)))
    if not found:
        raise ValueError("COMMANDS registry is empty")
    return found


def doc_files(root: Path) -> list[Path]:
    docs = root / "docs"
    files = [root / "README.md"] + (sorted(docs.glob("*.md")) if docs.is_dir() else [])
    return [p for p in files if p.is_file() and not p.is_symlink()]


def broken_links(root: Path, rels: list[str]) -> list[str]:
    base = root.resolve()
    out = []
    for rel in rels:
        page = root / rel
        if not page.is_file():
            continue
        for target in sorted(set(LINK.findall(_read(page)))):
            if re.match(r"[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith("#"):
                continue
            path = target.split("#", 1)[0].split("?", 1)[0]
            if not path:
                continue
            dest = (page.parent / path).resolve()
            try:
                dest.relative_to(base)
            except ValueError:
                out.append(f"{rel} -> {target} (escapes repository)")
                continue
            if not dest.exists():
                out.append(f"{rel} -> {target}")
    return out


def evaluate(root: Path) -> dict:
    if not root.is_dir():
        raise ValueError("root is not a directory")
    missing = [r for r in REQUIRED if not (root / r).is_file()]
    text = "\n".join(_read(p) for p in doc_files(root))
    undocumented = [c for c in commands(root)
                    if not re.search(r"onecompany\.py\s+" + re.escape(c) + r"(?![\w-])", text)]
    return {"required_missing": missing, "broken_links": broken_links(root, list(REQUIRED)),
            "undocumented_commands": undocumented}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only documentation check.")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args(argv)
    try:
        result = evaluate(Path(args.root))
    except ValueError as exc:
        print(f"docs-check: UNABLE TO VERIFY ({exc})", file=sys.stderr)
        return 2
    labels = (("required_missing", "REQUIRED_MISSING"), ("broken_links", "BROKEN_LINK"),
              ("undocumented_commands", "UNDOCUMENTED_COMMAND"))
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print("docs-check: " + ", ".join(f"{len(result[k])} {k.replace('_', ' ')}" for k, _ in labels))
        for key, label in labels:
            for item in result[key]:
                print(f"  {label} {item}")
    return 1 if any(result[k] for k, _ in labels) else 0


if __name__ == "__main__":
    sys.exit(main())
