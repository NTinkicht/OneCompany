#!/usr/bin/env python3
"""Read-only resume view for an exported OneCompany Product Brief draft."""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

from product_brief import FIELDS, REQUIRED, checked_answer

MAX_BYTES = 16_384
TOP_LEVEL = frozenset({
    "schema_version", "document_kind", "status", "source", "project",
    "answers", "missing_required_answers", "acceptance_criteria", "approval",
    "write_lease_granted", "qualified_implementer_selected",
    "safety_blockers", "next_action",
})
PROJECT_KEYS = frozenset({
    "name", "repository", "default_branch", "path",
    "known_stack", "existing_tests", "existing_ci", "known_contracts",
})
PROJECT_LISTS = ("known_stack", "existing_tests", "existing_ci", "known_contracts")


def _read_json(path: Path) -> dict:
    """Use anchored, no-follow directory and file FDs with bounded reads."""
    if not getattr(os, "O_NOFOLLOW", 0) or not getattr(os, "O_DIRECTORY", 0) or not getattr(os, "O_NONBLOCK", 0):
        raise ValueError("secure resume requires O_NOFOLLOW/O_DIRECTORY")
    parts = path.parts[1:] if path.is_absolute() else path.parts
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise ValueError("unsafe draft path")
    dirs: list[int] = []
    try:
        dirs.append(os.open(path.anchor if path.is_absolute() else ".",
                            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW))
        for component in parts[:-1]:
            dirs.append(os.open(component,
                                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=dirs[-1]))
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=dirs[-1])
        try:
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_BYTES:
                raise ValueError("draft must be a regular file no larger than 16384 bytes")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                raw = stream.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("draft must be a regular file no larger than 16384 bytes")
        finally:
            os.close(fd)
    finally:
        for fd in reversed(dirs):
            os.close(fd)
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("draft must be a JSON object")
    return data


def load_draft(path: Path) -> dict:
    """Reject malformed or authority-bearing drafts before presenting resume."""
    data = _read_json(path)
    if set(data) != TOP_LEVEL:
        raise ValueError("draft has unknown or missing authority-related fields")
    if (data["schema_version"] != "1.0"
            or data["document_kind"] != "product_brief_draft"
            or data["status"] != "DRAFT_NOT_APPROVED"
            or data["source"] != "owner_supplied_answers_and_read_only_discovery"):
        raise ValueError("unsupported Product Brief schema or kind")
    approval = data["approval"]
    if (not isinstance(approval, dict)
            or set(approval) != {"product_brief", "implementation", "deployment"}
            or any(approval[name] is not False for name in
                   ("product_brief", "implementation", "deployment"))):
        raise ValueError("draft contains authority or malformed approval state")
    if (data["write_lease_granted"] is not False
            or data["qualified_implementer_selected"] is not False
            or data["acceptance_criteria"] != []):
        raise ValueError("draft contains implementation authority or unapproved criteria")
    if data["safety_blockers"] != []:
        raise ValueError("draft has discovery safety blockers")
    project = data["project"]
    if not isinstance(project, dict) or set(project) != PROJECT_KEYS:
        raise ValueError("draft has malformed project/discovery facts")
    if project["path"] not in ("create", "adopt"):
        raise ValueError("draft project path invalid")
    if any(not isinstance(project[k], str) or not project[k] for k in
           ("name", "repository", "default_branch")):
        raise ValueError("draft project identity invalid")
    if any(not isinstance(project[k], list) or
           any(not isinstance(v, str) for v in project[k])
           for k in PROJECT_LISTS):
        raise ValueError("draft project discovery assets invalid")
    answers = data["answers"]
    if not isinstance(answers, dict) or set(answers) != set(FIELDS):
        raise ValueError("draft answers are missing or malformed")
    for name, (_, limit) in FIELDS.items():
        value = answers[name]
        if checked_answer(value, limit) != value:
            raise ValueError("draft owner answer invalid or unbounded")
    missing = [name for name in REQUIRED if not answers[name]]
    if data["missing_required_answers"] != missing:
        raise ValueError("draft contradicts required owner answers")
    expected_next = (
        "Provide the missing required owner answers; do not begin implementation."
        if missing else
        "Review this draft and propose acceptance criteria through the existing "
        "trusted OneCompany planning process; saving is NOT approval."
    )
    if data["next_action"] != expected_next:
        raise ValueError("draft next action contradicts owner input")
    return data


def summarize(data: dict) -> dict:
    """Return safe guidance without claiming approval, readiness or a lease."""
    answers = data["answers"]
    missing = list(data["missing_required_answers"])
    return {
        "status": "DRAFT_NOT_APPROVED",
        "project": data["project"]["name"],
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
    """Present bounded and validated saved owner draft as an unapproved view."""
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
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        print("REFUSED: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
