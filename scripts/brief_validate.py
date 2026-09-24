#!/usr/bin/env python3
"""Read-only structural validation for an explicitly saved Product Brief JSON file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from first_run_journey import read_brief
from product_brief import FIELDS, REQUIRED

CANONICAL = {
    "schema_version": "1.0",
    "document_kind": "product_brief_draft",
    "status": "DRAFT_NOT_APPROVED",
    "source": "owner_supplied_answers_and_read_only_discovery",
}


def validate(path: Path) -> dict[str, object]:
    """Validate the canonical saved-draft envelope without granting authority.

    The journey command remains the stronger check because it additionally
    recreates the draft from current discovery and requires full equality.
    """
    try:
        data = read_brief(path)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        message = str(exc)
        if "TOO_LARGE" in message:
            status = "REFUSED_OVERSIZED"
        elif "FILE_REQUIRED" in message or "SECURE_BRIEF_READ_UNAVAILABLE" in message:
            status = "REFUSED_UNSAFE_PATH"
        else:
            status = "REFUSED_MALFORMED"
        return {"valid": False, "status": status}

    if any(data.get(key) != value for key, value in CANONICAL.items()):
        return {"valid": False, "status": "REFUSED_WRONG_KIND"}
    project = data.get("project")
    answers = data.get("answers")
    if not isinstance(project, dict) or not isinstance(answers, dict):
        return {"valid": False, "status": "REFUSED_WRONG_KIND"}
    if any(key not in project for key in (
        "name", "repository", "default_branch", "path", "known_stack",
        "existing_tests", "existing_ci", "known_contracts",
    )):
        return {"valid": False, "status": "REFUSED_WRONG_KIND"}
    if any(key not in answers for key in FIELDS):
        return {"valid": False, "status": "REFUSED_WRONG_KIND"}

    approval = data.get("approval")
    if approval != {
        "product_brief": False,
        "implementation": False,
        "deployment": False,
    }:
        return {"valid": False, "status": "REFUSED_AUTHORITY_BEARING"}
    if data.get("write_lease_granted") is not False:
        return {"valid": False, "status": "REFUSED_AUTHORITY_BEARING"}
    if data.get("qualified_implementer_selected") is not False:
        return {"valid": False, "status": "REFUSED_AUTHORITY_BEARING"}
    if data.get("acceptance_criteria") != []:
        return {"valid": False, "status": "REFUSED_AUTHORITY_BEARING"}

    missing = [
        key for key in REQUIRED
        if not isinstance(answers.get(key), str) or not answers[key].strip()
    ]
    declared_missing = data.get("missing_required_answers")
    if declared_missing != missing:
        return {"valid": False, "status": "REFUSED_STALE_DERIVATION"}
    return {
        "valid": not missing,
        "status": "PROPOSAL_READY_NOT_APPROVED" if not missing else "INCOMPLETE_NOT_APPROVED",
        "missing": missing,
        "approved": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("brief", type=Path)
    args = parser.parse_args()
    result = validate(args.brief)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
