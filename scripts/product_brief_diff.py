#!/usr/bin/env python3
"""Read-only preview of two owner Product Brief drafts; no execution authority."""
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


def _read_bounded(path: Path) -> dict:
    """Open every path component without following links; read one bounded FD."""
    if (not getattr(os, "O_NOFOLLOW", 0) or not getattr(os, "O_DIRECTORY", 0)
            or not getattr(os, "O_NONBLOCK", 0)):
        raise ValueError("secure Product Brief reading requires O_NOFOLLOW/O_DIRECTORY")
    parts = path.parts[1:] if path.is_absolute() else path.parts
    if not parts or any(p in ("", ".", "..") for p in parts):
        raise ValueError("unsafe Product Brief path")
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
            meta = os.fstat(fd)
            if not stat.S_ISREG(meta.st_mode) or meta.st_size > MAX_BYTES:
                raise ValueError("Product Brief must be a regular bounded file")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                raw = stream.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("Product Brief exceeds 16384 bytes")
        finally:
            os.close(fd)
    finally:
        for fd in reversed(dirs):
            os.close(fd)
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Product Brief must be a JSON object")
    return data


def validate(data: dict) -> dict:
    """Validate the whole producer draft contract, not just the display fields."""
    if not isinstance(data, dict) or set(data) != TOP_LEVEL:
        raise ValueError("Product Brief has missing or unknown authority-bearing fields")
    if (data["schema_version"] != "1.0"
            or data["document_kind"] != "product_brief_draft"
            or data["status"] != "DRAFT_NOT_APPROVED"
            or data["source"] != "owner_supplied_answers_and_read_only_discovery"):
        raise ValueError("unsupported Product Brief draft")
    approval = data["approval"]
    if (not isinstance(approval, dict)
            or set(approval) != {"product_brief", "implementation", "deployment"}
            or any(approval[name] is not False for name in
                   ("product_brief", "implementation", "deployment"))
            or data["write_lease_granted"] is not False
            or data["qualified_implementer_selected"] is not False
            or data["acceptance_criteria"] != []):
        raise ValueError("Product Brief contains authority-bearing state")
    blockers = data["safety_blockers"]
    if not isinstance(blockers, list) or any(not isinstance(b, str) for b in blockers):
        raise ValueError("invalid Product Brief safety blockers")
    project = data["project"]
    if not isinstance(project, dict) or set(project) != PROJECT_KEYS:
        raise ValueError("invalid Product Brief project")
    if project["path"] not in ("create", "adopt"):
        raise ValueError("invalid Product Brief project path")
    if any(not isinstance(project[key], str) or not project[key] for key in
           ("name", "repository", "default_branch")):
        raise ValueError("invalid Product Brief project identity")
    if any(not isinstance(project[key], list) or
           any(not isinstance(item, str) for item in project[key])
           for key in PROJECT_LISTS):
        raise ValueError("invalid Product Brief discovery assets")
    answers = data["answers"]
    if not isinstance(answers, dict) or set(answers) != set(FIELDS):
        raise ValueError("invalid owner answers")
    for key, (_, limit) in FIELDS.items():
        value = answers[key]
        if checked_answer(value, limit) != value:
            raise ValueError("invalid unnormalized or unbounded owner answer")
    missing = [k for k in REQUIRED if not answers[k]]
    if data["missing_required_answers"] != missing:
        raise ValueError("inconsistent Product Brief required answers")
    next_action = (
        "Provide the missing required owner answers; do not begin implementation."
        if missing else
        "Review this draft and propose acceptance criteria through the existing "
        "trusted OneCompany planning process; saving is NOT approval."
    )
    if data["next_action"] != next_action:
        raise ValueError("inconsistent Product Brief next action")
    return data


def load(path: Path) -> dict:
    """Reject unsafe paths and validate a complete unapproved Product Brief."""
    return validate(_read_bounded(path))


def compare(before: dict, after: dict) -> dict:
    """Compare only explicit owner answers belonging to the same discovered project."""
    validate(before)
    validate(after)
    if before["project"] != after["project"]:
        raise ValueError("Product Brief project/discovery mismatch")
    changes = []
    for field in FIELDS:
        old, new = before["answers"][field], after["answers"][field]
        if old != new:
            changes.append({"field": field, "before": old, "after": new})
    return {
        "status": "PREVIEW_ONLY_NOT_APPROVED",
        "changed_fields": changes,
        "implementation_authorized": False,
        "next_action": "Owner reviews these draft changes; use the trusted planning process before any implementation.",
    }


def main(argv: list[str] | None = None) -> int:
    """Print safe owner-answer changes without saving, approving or editing."""
    parser = argparse.ArgumentParser(
        description="Preview changes between two unapproved Product Brief drafts")
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = compare(load(args.before), load(args.after))
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("OneCompany Product Brief change preview - NOT APPROVED")
            if not result["changed_fields"]:
                print("No owner-answer changes.")
            for item in result["changed_fields"]:
                print(f"{item['field']}: {item['before']!r} -> {item['after']!r}")
            print("Next: " + result["next_action"])
        return 0
    except (OSError, ValueError, UnicodeError, TypeError) as exc:
        print("REFUSED: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
