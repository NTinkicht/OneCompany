#!/usr/bin/env python3
"""Copy the reusable OneCompany control plane into another repository."""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from onecompany_lib import ROOT

COPY_PATHS = [
    ".onecompany",
    "agents",
    "company",
    "patterns",
    "overlays",
    "docs",
    "scripts",
    "onecompany.py",
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    ".github/copilot-instructions.md",
    ".github/ISSUE_TEMPLATE",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/workflows/onecompany-validate.yml",
]


def copy_item(source: Path, target: Path, force: bool) -> None:
    if source.is_dir():
        for child in source.rglob("*"):
            if child.is_dir():
                continue
            relative = child.relative_to(source)
            copy_item(child, target / relative, force)
        return
    if target.exists() and not force:
        raise FileExistsError(f"refusing to overwrite {target}; use --force only after review")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap OneCompany into an existing repository")
    parser.add_argument("--target", required=True, help="Path to target repository")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    target = Path(args.target).resolve()
    target.mkdir(parents=True, exist_ok=True)

    try:
        for relative in COPY_PATHS:
            source = ROOT / relative
            if not source.exists():
                print(f"SKIP missing source {relative}")
                continue
            copy_item(source, target / relative, args.force)
    except FileExistsError as exc:
        print(f"ERROR: {exc}")
        return 2

    print(f"OneCompany files copied to {target}")
    print("Next: configure project/budget/actors/readiness/routing/supervision; then run doctor, validate, simulate and first-run acceptance drills.")
    print("Unattended workflow templates remain under .onecompany/templates and are NOT activated automatically.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
