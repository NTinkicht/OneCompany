#!/usr/bin/env python3
"""Read-only live GitHub reconciliation command (OC-P0-01, #521).

Chains the injected-transport pieces ``make_gh_fetch`` (#402) and ``reconcile_live`` (#397)
behind one CLI so the live capture is actually runnable. Inputs file is a JSON object with
exactly: main_sha, pulls, active_lease_issue_ids, retired_pilot_issue_ids, write_attempts,
trusted_reviewers, app_slugs. Only GET ``gh api`` argv built by ``make_gh_fetch`` is run
(no shell, bounded timeout). Exit 0 CONSISTENT, 1 INCONSISTENT, 2 UNABLE TO VERIFY.
Refusals print a fixed message and never response content.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from github_gh_fetch import make_gh_fetch  # noqa: E402
from github_live_reconcile import LiveReconciliationRefused, reconcile_live  # noqa: E402
from github_page_capture import CaptureError, DEFAULT_MAX_PAGES  # noqa: E402
from live_reconciliation_report import DEFAULT_MAX_AGE_SECONDS, render  # noqa: E402

KEYS = frozenset({"main_sha", "pulls", "active_lease_issue_ids", "retired_pilot_issue_ids",
                  "write_attempts", "trusted_reviewers", "app_slugs"})
REPO = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}")
TIMEOUT_SECONDS = 60


def subprocess_runner(argv: list[str]) -> tuple[int, str]:
    done = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=False)
    return done.returncode, done.stdout


def _reject_duplicate_keys(pairs):
    """json keeps the last repeated key, which could forge a reconciliation input; refuse it."""
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate key in JSON input")
    return dict(pairs)


def load_inputs(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (OSError, ValueError, RecursionError):
        raise ValueError("inputs unreadable or not JSON") from None
    if not isinstance(data, dict) or set(data) != KEYS:
        raise ValueError("inputs must be an object with exactly the required keys")
    return data


def main(argv: list[str] | None = None, runner: Callable | None = None,
         clock: Callable[[], dt.datetime] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only live GitHub reconciliation (gh api GET only).")
    parser.add_argument("--repo", required=True, help="OWNER/REPO to reconcile")
    parser.add_argument("--inputs", required=True, type=Path, help="JSON file with the caller baseline")
    parser.add_argument("--max-age-seconds", type=int, default=DEFAULT_MAX_AGE_SECONDS)
    args = parser.parse_args(argv)
    try:
        if not REPO.fullmatch(args.repo):
            raise ValueError("invalid repo")
        data = load_inputs(args.inputs)
        clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))
        started = clock()
        report = reconcile_live(
            make_gh_fetch(runner or subprocess_runner), args.repo, data["pulls"], now=clock,
            observed_at=started.isoformat(), main_sha=data["main_sha"],
            active_lease_issue_ids=data["active_lease_issue_ids"],
            retired_pilot_issue_ids=data["retired_pilot_issue_ids"],
            write_attempts=data["write_attempts"], trusted_reviewers=data["trusted_reviewers"],
            app_slugs=data["app_slugs"], max_pages=DEFAULT_MAX_PAGES,
            max_age_seconds=args.max_age_seconds)
    except (ValueError, LiveReconciliationRefused, CaptureError) as exc:
        reason = str(exc) if isinstance(exc, LiveReconciliationRefused) or type(exc) is ValueError else "refused"
        print(f"live-reconcile: UNABLE TO VERIFY ({reason})", file=sys.stderr)
        return 2
    sys.stdout.write(render(report))
    return 0 if report["status"] == "CONSISTENT" else 1


if __name__ == "__main__":
    sys.exit(main())
