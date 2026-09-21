#!/usr/bin/env python3
"""Draft an owner-editable Product Brief from read-only Create/Adopt discovery.

This is product intake, not an approval, execution plan, or implementation lease.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from onboard import analyze

FIELDS = {
    "audience": "audience",
    "problem": "problem",
    "outcome": "first_valuable_outcome",
    "first_feature": "first_feature",
}
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


def clean_answer(value: str | None, field: str) -> str | None:
    if value is None or not value.strip():
        return None
    answer = value.strip()
    if len(answer) > 500 or any(ord(c) < 32 or ord(c) == 127 for c in answer):
        raise ValueError(f"{field}: answer must be <=500 characters without control characters")
    return answer


def draft(report: dict, answers: dict[str, str | None]) -> dict:
    """Retain discovered facts exactly, keep unknown intent unknown."""
    journey = report["journey"]
    brief = dict(journey["product_brief_draft"])
    for source, destination in FIELDS.items():
        brief[destination] = clean_answer(answers.get(source), source)
    missing = [key for key, destination in FIELDS.items() if brief[destination] is None]
    return {
        "version": 1,
        "kind": "onecompany_product_brief",
        "source": "read_only_onboard_assessment",
        "mode": report["mode"],
        "path": journey["path"],
        "status": "DRAFT_NOT_APPROVED",
        "proposed_only": True,
        "approved": False,
        "application_authorized": False,
        "write_lease_granted": False,
        "actor_qualified": False,
        "safety_blockers": list(report["blockers"]),
        "missing_fields": missing,
        "brief": brief,
    }


def exclusive_save(path: Path, value: dict) -> None:
    """Fail closed rather than overwriting an existing file or following a final symlink."""
    data = (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="Propose an unapproved Product Brief")
    parser.add_argument("--target", default=".")
    parser.add_argument("--repository")
    parser.add_argument("--project-name")
    parser.add_argument("--default-branch")
    for field in FIELDS:
        parser.add_argument("--" + field.replace("_", "-"))
    parser.add_argument("--save-to", help="Explicitly write a new private JSON file; never overwrite")
    parser.add_argument("--json", action="store_true", help="Emit the complete draft JSON")
    args = parser.parse_args()
    if args.repository and not REPOSITORY.fullmatch(args.repository):
        parser.error("--repository must be OWNER/REPO")
    target = Path(args.target).resolve()
    try:
        report = analyze(target, args.repository, args.project_name, args.default_branch)
        result = draft(report, {key: getattr(args, key) for key in FIELDS})
    except (OSError, ValueError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Product Brief for {result['brief']['project_name']}: DRAFT, NOT APPROVED")
        print(f"Create/Adopt path: {result['path']}")
        for key in FIELDS:
            print(f"{key}: {result['brief'][FIELDS[key]] or '[owner input needed]'}")
        print("Missing fields: " + (", ".join(result["missing_fields"]) or "none"))
        print("Safety blockers: " + (", ".join(result["safety_blockers"]) or "none"))
        print("No approval, lease, target mutation or model/API call has occurred.")
    if args.save_to:
        if result["safety_blockers"]:
            print("REFUSED: resolve onboarding blockers before saving", file=sys.stderr)
            return 2
        try:
            exclusive_save(Path(args.save_to), result)
        except (OSError, ValueError) as exc:
            print(f"REFUSED: could not exclusively save Product Brief: {exc}", file=sys.stderr)
            return 2
    return 0 if not result["safety_blockers"] else 2


if __name__ == "__main__":
    sys.exit(main())
