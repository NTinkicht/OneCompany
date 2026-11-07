#!/usr/bin/env python3
"""Deterministic, read-only acceptance-criterion coverage report (OC-P1-04, #435).

Reads the approved acceptance criteria in ``.onecompany/requirements-catalog.json``
and the ``# covers: AC-###`` comment annotations in test files. Reports which
approved criteria have no declaring test, which of those are negative/failure
cases, and annotations naming criteria absent from the catalog. Declaration is
not proof that a test passes; it is a traceability gap report. No network, no
writes, no clock.
"""

from __future__ import annotations

import argparse
import json
import re
import io
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEST_GLOBS = ("tests/test_*.py", ".onecompany/selftest/test_*.py")
ANNOTATION = re.compile(r"^\s*#\s*covers:\s*(AC-\d{3,}(?:\s*,\s*AC-\d{3,})*)\s*$")
AC_ID = re.compile(r"AC-\d{3,}")
AC_STATUSES = frozenset({"proposed", "approved", "verified", "retired"})


def load_catalog(root: Path) -> dict[str, dict]:
    """Return approved and non-approved ACs by id; raise ValueError on any malformed catalog."""
    try:
        data = json.loads((root / ".onecompany" / "requirements-catalog.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"catalog unreadable: {exc.__class__.__name__}") from exc
    items = data.get("acceptance_criteria") if isinstance(data, dict) else None
    if not isinstance(items, list) or not items:
        raise ValueError("catalog has no acceptance_criteria list")
    catalog: dict[str, dict] = {}
    for item in items:
        ident = item.get("id") if isinstance(item, dict) else None
        if not isinstance(ident, str) or not AC_ID.fullmatch(ident) or ident in catalog:
            raise ValueError("catalog has a malformed or duplicate acceptance criterion id")
        if item.get("status") not in AC_STATUSES:
            raise ValueError("catalog has an acceptance criterion with a missing or invalid status")
        catalog[ident] = item
    return catalog


def declarations(root: Path) -> dict[str, list[str]]:
    """Map AC id to the sorted repo-relative test files declaring it with a comment annotation."""
    found: dict[str, set[str]] = {}
    for pattern in TEST_GLOBS:
        for path in sorted(root.glob(pattern)):
            if path.is_symlink() or not path.is_file():
                continue
            try:
                source = path.read_text(encoding="utf-8")
                comments = [t for t in tokenize.generate_tokens(io.StringIO(source).readline)
                            if t.type == tokenize.COMMENT]
            except (OSError, UnicodeDecodeError, tokenize.TokenError, SyntaxError):
                continue
            rel = path.relative_to(root).as_posix()
            for token in comments:
                if token.line[: token.start[1]].strip():
                    continue  # trailing comment after code, not a standalone annotation line
                match = ANNOTATION.match(token.string)
                if match:
                    for ident in AC_ID.findall(match.group(1)):
                        found.setdefault(ident, set()).add(rel)
    return {key: sorted(value) for key, value in sorted(found.items())}


def report(root: Path) -> dict:
    """Build the sorted coverage report; raises ValueError when the catalog is unusable."""
    catalog = load_catalog(root)
    declared = declarations(root)
    approved = sorted(i for i, item in catalog.items() if item.get("status") == "approved")
    uncovered = [i for i in approved if i not in declared]
    return {
        "approved": len(approved),
        "covered": len(approved) - len(uncovered),
        "uncovered": uncovered,
        "uncovered_negative": [i for i in uncovered if catalog[i].get("negative_or_failure_case") is True],
        "unknown": sorted(i for i in declared if i not in catalog),
        "declarations": {i: declared[i] for i in approved if i in declared},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only acceptance-criterion coverage report.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    parser.add_argument("--strict", action="store_true", help="exit 1 on any uncovered or unknown criterion")
    args = parser.parse_args(argv)
    try:
        result = report(ROOT)
    except ValueError as exc:
        print(f"ac-coverage: UNABLE TO VERIFY ({exc})", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"ac-coverage: {result['covered']}/{result['approved']} approved criteria declared by a test")
        for ident in result["uncovered"]:
            tag = " (negative case)" if ident in result["uncovered_negative"] else ""
            print(f"  UNCOVERED {ident}{tag}")
        for ident in result["unknown"]:
            print(f"  UNKNOWN_AC {ident}")
    return 1 if args.strict and (result["uncovered"] or result["unknown"]) else 0


if __name__ == "__main__":
    sys.exit(main())
