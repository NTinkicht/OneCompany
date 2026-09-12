#!/usr/bin/env python3
"""Check whether the local environment can operate a OneCompany repository."""
from __future__ import annotations

import json
import platform
import sys
from pathlib import Path

from onecompany_lib import CONTROL, ROOT, command_exists, load_json, run


def line(ok: bool, label: str, detail: str = "") -> None:
    mark = "OK" if ok else "!!"
    suffix = f" — {detail}" if detail else ""
    print(f"[{mark}] {label}{suffix}")


def main() -> int:
    failures = 0
    line(sys.version_info >= (3, 10), "Python >= 3.10", platform.python_version())
    if sys.version_info < (3, 10):
        failures += 1

    for name, required in (("git", True), ("gh", False), ("node", False), ("npm", False)):
        exists = command_exists(name)
        line(exists, name, "required" if required else "optional but useful")
        if required and not exists:
            failures += 1

    for relative in ("config.json", "actors.json", "roles.json", "budget.json", "state.json", "queue.json"):
        path = CONTROL / relative
        try:
            load_json(path)
            line(True, str(path.relative_to(ROOT)), "valid JSON")
        except Exception as exc:
            line(False, str(path.relative_to(ROOT)), str(exc))
            failures += 1

    if command_exists("git"):
        result = run(["git", "rev-parse", "--is-inside-work-tree"])
        line(result.returncode == 0, "Git worktree", result.stdout.strip() or result.stderr.strip())

    if command_exists("gh"):
        auth = run(["gh", "auth", "status"])
        line(auth.returncode == 0, "GitHub CLI authentication", "authenticated" if auth.returncode == 0 else "not authenticated")

    print("\nDoctor result:", "READY" if failures == 0 else f"{failures} blocking problem(s)")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
