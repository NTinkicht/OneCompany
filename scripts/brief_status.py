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
    """Classify a canonical saved Product Brief without granting authority."""
    try:
        data = read_brief(path)
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError, ValueError):
        return _blocked("unsafe_or_malformed_brief", "recreate_saved_brief")

    return summarize_data(data)


def summarize_data(data: object) -> dict[str, object]:
    """Classify ONE already-securely-read saved draft without reopening its path."""
    if not isinstance(data, dict):
        return _blocked("unsafe_or_malformed_brief", "recreate_saved_brief")

    answers = data.get("answers")
    if not isinstance(answers, dict):
        return _blocked("missing_answers_object", "recreate_saved_brief")

    approval = data.get("approval")
    canonical_approval = {
        "product_brief": False,
        "implementation": False,
        "deployment": False,
    }
    acceptance_criteria = data.get("acceptance_criteria")
    authority_bearing = (
        data.get("schema_version") != "1.0"
        or data.get("document_kind") != "product_brief_draft"
        or data.get("status") != "DRAFT_NOT_APPROVED"
        or data.get("source") != "owner_supplied_answers_and_read_only_discovery"
        or not isinstance(data.get("project"), dict)
        or approval != canonical_approval
        or acceptance_criteria != []
        or "run_key" in data
        or data.get("approved") is True
        or data.get("deployment_authorized") is True
        or data.get("write_lease_granted") is not False
        or data.get("qualified_implementer_selected") is not False
    )
    if authority_bearing:
        return _blocked(
            "authority_bearing_or_noncanonical_brief",
            "recreate_saved_brief_from_read_only_discovery",
        )

    missing = [
        key
        for key in REQUIRED
        if not isinstance(answers.get(key), str) or not answers[key].strip()
    ]
    saved_missing = data.get("missing_required_answers")
    if saved_missing != missing:
        return _blocked(
            "inconsistent_missing_required_answers",
            "recreate_saved_brief_from_read_only_discovery",
        )

    safety_blockers = data.get("safety_blockers")
    if not isinstance(safety_blockers, list) or any(
        not isinstance(blocker, str) or not blocker.strip()
        for blocker in safety_blockers
    ):
        return _blocked("invalid_safety_blockers", "recreate_saved_brief")

    if safety_blockers:
        return {
            "stage": "BLOCKED",
            "missing": missing,
            "blockers": safety_blockers,
            "next_action": "resolve_discovery_safety_blockers",
            "approved": False,
        }

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
