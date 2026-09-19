#!/usr/bin/env python3
"""Reject client runtime evidence only from the generic OneCompany source."""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_REPOSITORY = "NTinkicht/OneCompany"
FORBIDDEN = ("source-evidence", "evidence")


def current_repository() -> str | None:
    # GitHub supplies authoritative workflow repository identity. In an
    # installed client repository this is the client's name, not OneCompany.
    workflow_repo = os.environ.get("GITHUB_REPOSITORY")
    if workflow_repo:
        return workflow_repo
    result = subprocess.run(
        ["git", "-C", str(ROOT), "remote", "get-url", "origin"],
        check=False, capture_output=True, text=True,
    )
    if result.returncode == 0:
        match = re.search(r"github\\.com[:/]([^/]+)/([^/]+?)(?:\\.git)?$", result.stdout.strip())
        if match:
            return f"{match.group(1)}/{match.group(2)}"
    # Offline source tree / uninitialized template: fail closed until the
    # project's own explicit bootstrap or init rebinds its configuration.
    config_path = ROOT / ".onecompany" / "config.json"
    if config_path.is_file():
        data = json.loads(config_path.read_text(encoding="utf-8"))
        return data.get("project", {}).get("repository")
    return None


def main() -> int:
    repository = current_repository()
    if repository is None:
        print("REFUSED: cannot establish repository identity for neutrality check")
        return 2
    if repository != SOURCE_REPOSITORY:
        print("PASS: installed project owns its own runtime evidence")
        return 0
    forbidden = [name for name in FORBIDDEN if (ROOT / name).exists() or (ROOT / name).is_symlink()]
    if forbidden:
        print("REFUSED: client runtime evidence bundled in generic source: " + ", ".join(forbidden))
        return 1
    print("PASS: generic OneCompany source contains no client runtime evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
