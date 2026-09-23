#!/usr/bin/env python3
"""Read-only resume view for an exported OneCompany Product Brief draft."""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

MAX_BYTES = 16_384
REQUIRED = ("audience", "problem", "outcome", "first_feature")


def load_draft(path: Path) -> dict:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_BYTES:
            raise ValueError("draft must be a regular file no larger than 16384 bytes")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("draft must be a regular file no larger than 16384 bytes")
        data = json.loads(raw.decode("utf-8"))
    finally:
        os.close(fd)
    if not isinstance(data, dict):
        raise ValueError("draft must be a JSON object")
    if data.get("schema_version") != "1.0" or data.get("document_kind") != "product_brief_draft":
        raise ValueError("unsupported Product Brief schema or kind")
    if data.get("status") != "DRAFT_NOT_APPROVED":
        raise ValueError("resume accepts only DRAFT_NOT_APPROVED briefs")
    answers = data.get("answers")
    if not isinstance(answers, dict):
        raise ValueError("draft answers are missing")
    approval = data.get("approval")
    if approval != {"product_brief": False, "implementation": False, "deployment": False}:
        raise ValueError("draft contains authority or malformed approval state")
    if data.get("write_lease_granted") is not False:
        raise ValueError("draft must not grant a write lease")
    if data.get("qualified_implementer_selected") is not False:
        raise ValueError("draft must not select a qualified implementer")
    return data


def summarize(data: dict) -> dict:
    answers = data["answers"]
    missing = [name for name in REQUIRED if not isinstance(answers.get(name), str) or not answers[name].strip()]
    project = data.get("project") if isinstance(data.get("project"), dict) else {}
    return {
        "status": "DRAFT_NOT_APPROVED",
        "project": project.get("name") or "unknown",
        "completed_required": [name for name in REQUIRED if name not in missing],
        "missing_required": missing,
        "implementation_authorized": False,
        "next_action": (
            "Provide the missing required owner answers; do not begin implementation."
            if missing else
            "Review the draft through the trusted OneCompany planning process; this resume view grants no approval."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Safely resume a saved OneCompany Product Brief draft")
    parser.add_argument("draft", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = summarize(load_draft(args.draft))
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("OneCompany Product Brief - RESUME, NOT APPROVED")
            print("Project: " + str(result["project"]))
            print("Completed required: " + (", ".join(result["completed_required"]) or "none"))
            print("Missing required: " + (", ".join(result["missing_required"]) or "none"))
            print("Next: " + result["next_action"])
        return 0 if not result["missing_required"] else 2
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        print("REFUSED: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
