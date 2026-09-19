#!/usr/bin/env python3
"""Fail closed if reusable OneCompany ships operational evidence for a target.

Client-specific release, migration, hosting and approval evidence must be owned
by the adopting project or its explicitly designated evidence store. Generic
synthetic fixtures are allowed only under the framework self-test directory.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROHIBITED_ROOTS = ("source-evidence/", "evidence/")
SYNTHETIC_FIXTURE_ROOT = ".onecompany/selftest/fixtures/"


def find_violations(paths: list[str], root: Path) -> list[str]:
    violations: list[str] = []
    for path in paths:
        normalized = path.replace("\\", "/").removeprefix("./")
        if normalized.startswith(PROHIBITED_ROOTS):
            violations.append(f"{normalized}: live target evidence is not core product material")
            continue
        if not normalized.startswith(SYNTHETIC_FIXTURE_ROOT) or not normalized.endswith(".json"):
            continue
        file = root / normalized
        try:
            payload = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            violations.append(f"{normalized}: unreadable synthetic fixture ({type(exc).__name__})")
            continue
        if not isinstance(payload, dict):
            violations.append(f"{normalized}: fixture must be a JSON object")
            continue
        project = payload.get("project", {})
        repository = project.get("repository") if isinstance(project, dict) else None
        snapshot = payload.get("snapshot", {})
        source = snapshot.get("source") if isinstance(snapshot, dict) else None
        if not isinstance(repository, str) or not repository.startswith("example/"):
            violations.append(f"{normalized}: fixture repository must use example/ namespace")
        if not isinstance(source, str) or not source.startswith("fixture-"):
            violations.append(f"{normalized}: fixture source must be explicitly synthetic")
        if not isinstance(payload.get("fixture_note"), str) or "synthetic" not in payload["fixture_note"].lower():
            violations.append(f"{normalized}: synthetic fixture must be visibly labelled")
    return violations


def main() -> int:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached"], cwd=ROOT,
        capture_output=True, check=False,
    )
    if result.returncode != 0:
        print("FAIL product-boundary: tracked-file inspection unavailable", file=sys.stderr)
        return 1
    tracked = [name.decode("utf-8") for name in result.stdout.split(b"\0") if name]
    problems = find_violations(tracked, ROOT)
    for problem in problems:
        print(f"FAIL product-boundary: {problem}", file=sys.stderr)
    if problems:
        return 1
    print(f"OneCompany product boundary PASS ({len(tracked)} tracked files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
