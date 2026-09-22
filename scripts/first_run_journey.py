#!/usr/bin/env python3
"""Read-only first-run Create/Adopt guidance over canonical onboarding and brief."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from onboard import analyze
from product_brief import FIELDS, make_draft

MAX_BRIEF_BYTES = 16_384


def read_brief(path: Path) -> dict:
    """Read one bounded owner-saved JSON draft without following a symlink."""
    if path.is_symlink() or not path.is_file():
        raise ValueError("SAVED_BRIEF_FILE_REQUIRED")
    with path.open("rb") as stream:
        raw = stream.read(MAX_BRIEF_BYTES + 1)
    if len(raw) > MAX_BRIEF_BYTES:
        raise ValueError("SAVED_BRIEF_TOO_LARGE")
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("SAVED_BRIEF_OBJECT_REQUIRED")
    return result


def view(assessment: dict, saved_brief: dict | None = None,
         brief_path: str | None = None) -> dict:
    """Explain next safe steps, never changing the real project's authority."""
    journey = assessment["journey"]
    blocked = bool(assessment["blockers"] or journey["path"] == "blocked")
    answers = {name: None for name in FIELDS}
    stage = "BLOCKED" if blocked else "NEEDS_PRODUCT_BRIEF"
    missing = ["audience", "problem", "outcome", "first_feature"]
    if saved_brief is not None:
        if blocked:
            raise ValueError("DISCOVERY_BLOCKED")
        if not isinstance(saved_brief.get("answers"), dict):
            raise ValueError("SAVED_BRIEF_ANSWERS_REQUIRED")
        answers = saved_brief["answers"]
        expected = make_draft(assessment, answers)
        # Full equality prevents stale discovery facts, fake approval, RunKeys,
        # leases, injected AC, unknown authority fields and malformed answers.
        if saved_brief != expected:
            raise ValueError("SAVED_BRIEF_STALE_OR_AUTHORITY_BEARING")
        missing = list(expected["missing_required_answers"])
        stage = "NEEDS_OWNER_ANSWERS" if missing else "PROPOSAL_READY_NOT_APPROVED"
    target = str(assessment["target"])
    repository = assessment.get("repository")
    brief_cmd = ["python", "onecompany.py", "brief", "--target", target]
    if repository:
        brief_cmd.extend(["--repository", repository])
    if saved_brief is None:
        next_commands = [brief_cmd + ["--json"]]
    elif missing:
        next_commands = [brief_cmd + ["--json"]]  # Rebuild the draft explicitly.
    else:
        next_commands = [[
            "python", "scripts/brief_handoff_proposal.py", "--brief",
            str(brief_path or "<SAVED_BRIEF_JSON>"),
            "--head", "<LIVE_HEAD_SHA>", "--base", "<LIVE_BASE_SHA>",
        ]]
    if blocked:
        next_commands = [["python", "onecompany.py", "onboard",
                          "--target", target, "--json"]]
        if repository:
            next_commands[0].extend(["--repository", repository])
    steps = [dict(step) for step in journey["steps"]]
    for step in steps:
        if step["id"] == "brief":
            step["status"] = (
                "blocked" if blocked else "complete_draft_not_approved"
                if stage == "PROPOSAL_READY_NOT_APPROVED"
                else "needs_input"
            )
    return {
        "schema": "onecompany.first-run-journey.v1",
        "read_only": True,
        "stage": stage,
        "path": journey["path"],
        "project": {
            "name": assessment["project_name"],
            "repository": repository,
            "target": target,
            "default_branch": assessment["default_branch"],
            "stack": list(assessment["stack"]),
            "tests": list(assessment["tests"]),
            "ci": list(assessment["ci"]),
            "contracts": [key for key, present in assessment["contracts"].items()
                          if present],
        },
        "answers": {name: answers.get(name) for name in FIELDS},
        "missing_required_answers": missing,
        "blockers": list(assessment["blockers"]),
        "steps": steps,
        "next_commands_argv": next_commands,
        "next_action": (
            "Resolve discovery blockers; no installation or execution is authorized."
            if blocked else
            "Answer and save a Product Brief explicitly; saving is not approval."
            if stage != "PROPOSAL_READY_NOT_APPROVED" else
            "Review a READ-ONLY proposed handoff; live refs and owner approval "
            "must be verified separately before any Work Unit executes."
        ),
        "approval": "NOT_GRANTED",
        "run_key": None,
        "lease_id": None,
        "canonical_work_unit": None,
        "model_qualified": False,
        "deployment_ready": False,
        "requested_extra_spend": 0,
    }


def main(argv: list[str] | None = None) -> int:
    """Inspect a target and optional saved brief; print clear next actions."""
    parser = argparse.ArgumentParser(description="OneCompany guided first-run status")
    parser.add_argument("--target", default=".")
    parser.add_argument("--repository")
    parser.add_argument("--brief", type=Path, help="Previously saved draft JSON")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        assessment = analyze(Path(args.target).resolve(), repository=args.repository)
        saved = read_brief(args.brief) if args.brief else None
        result = view(assessment, saved, str(args.brief) if args.brief else None)
    except (ValueError, OSError, TypeError, UnicodeError) as exc:
        print("REFUSED: " + str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("OneCompany - guided first run (read-only, NOT APPROVED)")
        print("Path: " + result["path"] + " | Stage: " + result["stage"])
        print("Project: " + str(result["project"]["name"]))
        for name in result["missing_required_answers"]:
            print("Needs your answer: " + FIELDS[name][0])
        for blocker in result["blockers"]:
            print("BLOCKED: " + blocker)
        print("Next: " + result["next_action"])
        print("Commands are guidance only; review arguments before running:")
        for command in result["next_commands_argv"]:
            print("  " + json.dumps(command))
    return 2 if result["stage"] != "PROPOSAL_READY_NOT_APPROVED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
