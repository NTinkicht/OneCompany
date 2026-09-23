#!/usr/bin/env python3
"""Summarize a saved Product Brief without granting authority."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REQUIRED = ("problem", "audience", "outcome", "first_feature")
MAX_BYTES = 128 * 1024


def _blocked(reason: str, next_action: str) -> dict[str, object]:
    """Return a bounded blocked status with an explicit safe next action."""
    return {
        "stage": "BLOCKED",
        "missing": [],
        "blockers": [reason],
        "next_action": next_action,
        "approved": False,
    }


def summarize(path: Path) -> dict[str, object]:
    """Classify a saved Product Brief without mutating or granting authority."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        return _blocked("unsafe_or_missing_brief", "recreate_saved_brief")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return _blocked("malformed_brief", "recreate_saved_brief")
    if not isinstance(data, dict):
        return _blocked("malformed_brief", "recreate_saved_brief")

    # Canonical Product Brief drafts keep owner answers under `answers`.
    # Do not silently accept legacy/top-level answer-shaped objects because that
    # would report a status for a file the real journey boundary would refuse.
    answers = data.get("answers")
    if not isinstance(answers, dict):
        return _blocked("missing_answers_object", "recreate_saved_brief")

    approval = data.get("approval")
    authority_bearing = (
        data.get("approved") is True
        or data.get("deployment_authorized") is True
        or data.get("write_lease_granted") is True
        or data.get("qualified_implementer_selected") is True
        or (
            isinstance(approval, dict)
            and any(value is True for value in approval.values())
        )
    )
    if authority_bearing:
        return _blocked("authority_bearing_brief", "remove_unverified_authority_and_revalidate")

    missing = [
        key
        for key in REQUIRED
        if not isinstance(answers.get(key), str) or not answers[key].strip()
    ]
    return {
        "stage": "DRAFT_INCOMPLETE" if missing else "DRAFT_COMPLETE_NOT_APPROVED",
        "missing": missing,
        "blockers": [],
        "next_action": "collect_owner_answers" if missing else "request_explicit_owner_decision",
        "approved": False,
    }


def main() -> int:
    """Print a read-only saved-brief status and return nonzero only if blocked."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("brief", type=Path)
    result = summarize(parser.parse_args().brief)
    print(json.dumps(result, sort_keys=True))
    return 2 if result["stage"] == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
