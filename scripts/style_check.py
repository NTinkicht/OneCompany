#!/usr/bin/env python3
"""Dependency-free readability/lint checks for the security-critical kernel."""
from __future__ import annotations

import io
import sys
import tokenize
from pathlib import Path

from onecompany_lib import ROOT

CRITICAL = (
    "scripts/assurance_gate.py",
    "scripts/evidence_verify.py",
    "scripts/gate.py",
    "scripts/ledger_lib.py",
    "scripts/lease.py",
    "scripts/lease_core.py",
    "scripts/lease_lifecycle.py",
    "scripts/merge.py",
    "scripts/platform_identity.py",
    "scripts/trusted_assurance.py",
)


def semicolon_lines(text: str) -> list[int]:
    result: list[int] = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        for token in tokens:
            if token.type == tokenize.OP and token.string == ";":
                result.append(token.start[0])
    except (IndentationError, tokenize.TokenError):
        return []
    return sorted(set(result))


def check_file(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
        compile(text, str(path), "exec")
    except (OSError, SyntaxError) as exc:
        return [f"{path.relative_to(ROOT)}: cannot compile: {exc}"]
    relative = path.relative_to(ROOT)
    for line in semicolon_lines(text):
        errors.append(f"{relative}:{line}: semicolon-packed statements are forbidden in critical kernel code")
    for number, raw in enumerate(text.splitlines(), 1):
        if "\t" in raw:
            errors.append(f"{relative}:{number}: tab indentation is forbidden")
        if raw.rstrip() != raw:
            errors.append(f"{relative}:{number}: trailing whitespace")
    return errors


def main() -> int:
    errors: list[str] = []
    checked = 0
    for relative in CRITICAL:
        path = ROOT / relative
        if not path.exists():
            # Some files are introduced by later stacked kernel WUs. Missing is
            # not a style failure on an earlier stack layer.
            continue
        checked += 1
        errors.extend(check_file(path))
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"Critical-kernel style FAILED ({len(errors)} error(s), {checked} files checked).")
        return 1
    print(f"Critical-kernel style PASS ({checked} files checked).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
