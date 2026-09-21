#!/usr/bin/env python3
"""Produce exact-revision quality evidence for the real local Phase-1 app."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_SHA = re.compile(r"^[0-9a-f]{40}$")
TEST = ROOT / ".onecompany" / "selftest" / "test_vertical_slice.py"


def _checkout_revision() -> str:
    """Return the exact clean checkout revision or fail closed."""
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=False
    )
    if head.returncode != 0 or not _SHA.fullmatch(head.stdout.strip()):
        raise ValueError("CHECKOUT_REVISION_UNAVAILABLE")
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if status.returncode != 0 or status.stdout.strip():
        raise ValueError("CLEAN_CHECKOUT_REQUIRED")
    return head.stdout.strip()


def collect(revision: str, timeout: float = 30.0) -> dict[str, object]:
    """Run the real HTTP/UI smoke only when revision equals the clean checkout HEAD."""
    if not isinstance(revision, str) or not _SHA.fullmatch(revision):
        raise ValueError("EXACT_REVISION_REQUIRED")
    if revision != _checkout_revision():
        raise ValueError("REVISION_CHECKOUT_MISMATCH")
    if not TEST.is_file():
        raise ValueError("LOCAL_APP_QUALITY_TEST_REQUIRED")
    try:
        result = subprocess.run(
            [sys.executable, str(TEST)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("LOCAL_APP_QUALITY_FAILED") from exc
    if result.returncode != 0:
        raise ValueError("LOCAL_APP_QUALITY_FAILED")
    return {
        "schema": "onecompany.local-quality-evidence.v1",
        "revision": revision,
        "status": "PASS",
        "scope": "real_local_http_ui",
        "test": ".onecompany/selftest/test_vertical_slice.py",
        "deployable": False,
    }


def main() -> int:
    """Run local quality assurance and print its non-deployable evidence."""
    parser = argparse.ArgumentParser(description="Capture exact-revision local app quality evidence")
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    print(json.dumps(collect(args.revision), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
