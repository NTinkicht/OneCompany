#!/usr/bin/env python3
"""Audit repository-wide workflow and template supply-chain invariants."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from onecompany_lib import ROOT

SHA40 = re.compile(r"^[0-9a-fA-F]{40}$")
USES = re.compile(r"(?m)^\s*-?\s*uses:\s*([^\s@]+)@([^\s#]+)")


def workflow_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".yml", ".yaml"}
    )


def audit_workflow(path: Path) -> list[str]:
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    relative = path.relative_to(ROOT)
    if re.search(r"(?m)^\s*pull_request_target\s*:", text):
        errors.append(f"{relative}: pull_request_target is forbidden")
    if re.search(r"(?mi)^\s*permissions\s*:\s*write-all\s*$", text):
        errors.append(f"{relative}: permissions: write-all is forbidden")
    for match in USES.finditer(text):
        action, revision = match.groups()
        if action.startswith("./"):
            continue
        if not SHA40.fullmatch(revision):
            errors.append(
                f"{relative}: external action {action}@{revision} is not pinned to immutable 40-hex SHA"
            )
    return errors


def main() -> int:
    errors: list[str] = []
    workflows = ROOT / ".github" / "workflows"
    discovered = workflow_files(workflows)
    if not discovered:
        errors.append(".github/workflows contains no executable workflow to audit")
    for path in discovered:
        errors.extend(audit_workflow(path))

    template_dir = ROOT / ".onecompany" / "templates" / "workflows"
    if template_dir.exists():
        for path in template_dir.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".yml", ".yaml"}:
                errors.append(
                    f"{path.relative_to(ROOT)}: provider/supervisor template became executable; "
                    "keep templates disabled until project setup explicitly promotes them"
                )

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"Hardening audit FAILED ({len(errors)} error(s)).")
        return 1
    print(f"Hardening audit PASS ({len(discovered)} workflow(s) audited).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
