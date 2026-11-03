#!/usr/bin/env python3
"""Deterministic, read-only release / incident readiness check (OC-P0-18, #421).

Verifies that the documented release and incident drills still match the
repository: every ``python onecompany.py <command>`` named in the release
checklist or the incident runbook is a registered command, the emergency-stop
flag is a boolean, the required sections exist and every referenced doc path
exists. No network, no writes, never clears the stop flag.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ("docs/RELEASE-CHECKLIST.md", "docs/INCIDENT-RUNBOOK.md")
REQUIRED_SECTIONS = {
    "docs/RELEASE-CHECKLIST.md": ("## Trusted control plane", "## Deterministic acceptance", "## Final promotion"),
    "docs/INCIDENT-RUNBOOK.md": ("## 1. Contain first", "## 4. Recover with a reversible path",
                                 "## 6. Restore autonomy gradually"),
}
COMMAND = re.compile(r"python3? onecompany\.py ([A-Za-z0-9_.:/-]+)")
DOC_PATH = re.compile(r"`((?:docs|scripts)/[A-Za-z0-9_./-]+\.(?:md|py|json))`")


def registered_commands(root: Path) -> set[str]:
    """Read the COMMANDS table of onecompany.py statically (never imports or executes it)."""
    tree = ast.parse((root / "onecompany.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "COMMANDS" for t in node.targets):
            if isinstance(node.value, ast.Dict):
                return {key.value for key in node.value.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)}
    return set()


def check(root: Path) -> list[str]:
    """Return sorted findings (stable codes); an empty list means ready."""
    findings: set[str] = set()
    commands = registered_commands(root)
    if not commands:
        findings.add("COMMAND_REGISTRY_UNREADABLE")
    try:
        config = json.loads((root / ".onecompany" / "config.json").read_text(encoding="utf-8"))
        flag = (config.get("safety") or {}).get("emergency_stop") if isinstance(config, dict) else None
    except (OSError, ValueError):
        flag = None
    if type(flag) is not bool:
        findings.add("EMERGENCY_STOP_NOT_BOOLEAN")
    for doc in DOCS:
        path = root / doc
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            findings.add(f"DOC_MISSING:{doc}")
            continue
        for section in REQUIRED_SECTIONS[doc]:
            if section not in text.splitlines():
                findings.add(f"SECTION_MISSING:{doc}:{section.lstrip('# ').strip()}")
        for command in COMMAND.findall(text):
            if commands and command not in commands:
                findings.add(f"UNKNOWN_COMMAND:{doc}:{command}")
        for ref in DOC_PATH.findall(text):
            if not (root / ref).is_file():
                findings.add(f"REFERENCED_PATH_MISSING:{doc}:{ref}")
    return sorted(findings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only release/incident readiness check.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args(argv)
    findings = check(ROOT)
    if args.json:
        print(json.dumps({"ready": not findings, "findings": findings}, sort_keys=True))
    elif findings:
        print("release-check: NOT READY")
        for finding in findings:
            print(f"  {finding}")
    else:
        print("release-check: READY (read-only; no stop flag cleared, no network)")
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
