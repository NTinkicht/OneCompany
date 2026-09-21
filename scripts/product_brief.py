#!/usr/bin/env python3
"""OneCompany owner-editable Product Brief; a draft is never execution authority."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from onboard import analyze

FIELDS = {
    "audience": ("Who will use it?", 400),
    "problem": ("Which problem do they have?", 1000),
    "outcome": ("What useful result should they achieve?", 1000),
    "first_feature": ("What is the smallest first useful feature?", 1000),
    "constraints": ("What privacy, data, accessibility and platform limits apply?", 1200),
}
REQUIRED = ("audience", "problem", "outcome", "first_feature")


def checked_answer(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("answers must be text")
    answer = value.strip()
    if len(answer) > limit or any(
        ord(char) < 32 and char not in "\t\n" for char in answer
    ):
        raise ValueError(f"answer must contain at most {limit} characters without control codes")
    return answer or None


def make_draft(assessment: dict[str, Any], answers: dict[str, str | None]) -> dict[str, Any]:
    """Derive a proposed brief from facts and explicit answers; no invented AC."""
    journey = assessment["journey"]
    origin = journey["product_brief_draft"]
    fields = {key: checked_answer(answers.get(key), limit)
              for key, (_, limit) in FIELDS.items()}
    missing = [name for name in REQUIRED if not fields[name]]
    return {
        "schema_version": "1.0",
        "document_kind": "product_brief_draft",
        "status": "DRAFT_NOT_APPROVED",
        "source": "owner_supplied_answers_and_read_only_discovery",
        "project": {
            "name": origin["project_name"],
            "repository": origin["repository"],
            "default_branch": origin["branch"],
            "path": journey["path"],
            "known_stack": list(origin["known_stack"]),
            "existing_tests": list(origin["existing_tests"]),
            "existing_ci": list(origin["existing_ci"]),
            "known_contracts": list(origin["known_contracts"]),
        },
        "answers": fields,
        "missing_required_answers": missing,
        "acceptance_criteria": [],
        "approval": {
            "product_brief": False,
            "implementation": False,
            "deployment": False,
        },
        "write_lease_granted": False,
        "qualified_implementer_selected": False,
        "safety_blockers": list(journey["safety_blockers"]),
        "next_action": (
            "Provide the missing required owner answers; do not begin implementation."
            if missing else
            "Review this draft and propose acceptance criteria through the existing "
            "trusted OneCompany planning process; saving is NOT approval."
        ),
    }


def save_exclusive(path: Path, draft: dict[str, Any]) -> None:
    """Explicit one-shot non-overwriting user export, never a canonical contract."""
    parent = path.parent
    if not parent.exists() or not parent.is_dir() or parent.is_symlink():
        raise ValueError("save parent must be an existing real directory")
    payload = (json.dumps(draft, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(payload) > 16_384:
        raise ValueError("draft exceeds export size limit")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Draft, review and explicitly export a Product Brief")
    parser.add_argument("--target", default=".")
    parser.add_argument("--repository", help="OWNER/REPO when remote inference is unavailable")
    for key, (description, _) in FIELDS.items():
        parser.add_argument("--" + key.replace("_", "-"), help=description)
    parser.add_argument("--save-to", type=Path, help="Create a NEW JSON draft file; never overwrites")
    parser.add_argument("--json", action="store_true", help="Print complete proposed brief")
    args = parser.parse_args(argv)
    try:
        assessment = analyze(Path(args.target).resolve(), repository=args.repository)
        answers = {name: getattr(args, name) for name in FIELDS}
        draft = make_draft(assessment, answers)
        if args.save_to:
            if draft["missing_required_answers"]:
                raise ValueError("cannot export incomplete brief: " +
                                 ", ".join(draft["missing_required_answers"]))
            save_exclusive(args.save_to, draft)
        if args.json:
            print(json.dumps(draft, ensure_ascii=False, indent=2))
        else:
            print("OneCompany Product Brief - PROPOSED, NOT APPROVED")
            print("Project: " + str(draft["project"]["name"]))
            for name, (question, _) in FIELDS.items():
                print(f"{question}  {draft['answers'][name] or '[needs your answer]'}")
            print("Next: " + draft["next_action"])
            if args.save_to:
                print("Draft exported to a new file: " + str(args.save_to))
        return 0 if not draft["missing_required_answers"] else 2
    except (ValueError, OSError) as exc:
        print("REFUSED: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
