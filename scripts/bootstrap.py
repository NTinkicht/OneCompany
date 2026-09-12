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

CONTRACTS = {
    "PRODUCT.md.template": "PRODUCT.md",
    "ARCHITECTURE.md.template": "ARCHITECTURE.md",
    "SECURITY.md.template": "SECURITY.md",
    "QUALITY.md.template": "QUALITY.md",
    "OPERATIONS.md.template": "OPERATIONS.md",
}


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


def initialize_contracts(target: Path) -> None:
    source_dir = ROOT / ".onecompany" / "templates" / "contracts"
    for source_name, target_name in CONTRACTS.items():
        source = source_dir / source_name
        destination = target / target_name
        if destination.exists():
            print(f"KEEP existing project contract {target_name}")
            continue
        shutil.copy2(source, destination)
        print(f"INIT project contract {target_name}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap OneCompany into an existing repository")
    parser.add_argument("--target", required=True, help="Path to target repository")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--initialize-contracts", action="store_true", help="Create missing PRODUCT/ARCHITECTURE/SECURITY/QUALITY/OPERATIONS contracts at target root")
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

    if args.initialize_contracts:
        initialize_contracts(target)

    print(f"OneCompany files copied to {target}")
    print("Next: configure project contracts, budget, actors, readiness, routing and supervision; then run doctor/validate/simulations and first-run acceptance drills.")
    print("Unattended workflow templates remain under .onecompany/templates and are NOT activated automatically.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
