#!/usr/bin/env python3
"""Summarize a saved Product Brief without granting authority."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from first_run_journey import read_brief

REQUIRED = ("problem", "audience", "outcome", "first_feature")


def _blocked(reason: str, next_action: str) -> dict[str, object]:
    """Return a bounded blocked status with an explicit safe next action."""
    return {
        "stage": "BLOCKED",
        "missing": list(REQUIRED),
        "blockers": [reason],
        "next_action": next_action,
        "approved": False,
    }


def summarize(path: Path) -> dict[str, object]:
    """Classify a saved Product Brief without mutating or granting authority."""
    try:
        data = read_brief(path)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return _blocked("unsafe_or_malformed_brief", "recreate_saved_brief")

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
        return _blocked(
            "authority_bearing_brief",
            "remove_unverified_authority_and_revalidate",
        )

    missing = [
        key
        for key in REQUIRED
        if not isinstance(answers.get(key), str) or not answers[key].strip()
    ]
    return {
        "stage": "DRAFT_INCOMPLETE" if missing else "DRAFT_COMPLETE_NOT_APPROVED",
        "missing": missing,
        "blockers": [],
        "next_action": "collect_owner_answers"
        if missing
        else "request_explicit_owner_decision",
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
