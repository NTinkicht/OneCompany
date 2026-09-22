#!/usr/bin/env python3
"""Interactive, read-only-first Create/Adopt Product Brief for new OneCompany users."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from onboard import analyze
from product_brief import FIELDS, REQUIRED, make_draft, save_exclusive


def collect(assessment: dict, *, input_fn=input, output_fn=print) -> dict:
    """Gather explicit owner answers, never guessing missing product requirements."""
    if assessment["blockers"] or assessment["journey"]["path"] not in ("create", "adopt"):
        raise ValueError("DISCOVERY_BLOCKED: " + "; ".join(assessment["blockers"]))
    output_fn("OneCompany — " + assessment["journey"]["path"].title() + " your project")
    output_fn("Project: " + assessment["project_name"])
    output_fn("Repository: " + str(assessment["repository"]))
    if assessment["journey"]["path"] == "adopt":
        output_fn("Existing stack: " + ", ".join(assessment["stack"]))
        output_fn("Existing tests: " + (", ".join(assessment["tests"]) or "none detected"))
        output_fn("Existing CI: " + (", ".join(assessment["ci"]) or "none detected"))
        output_fn("Your existing files and contracts will NOT be changed.")
    output_fn("Answer the owner Product Brief questions. Press Enter to leave a field blank.")
    answers = {}
    for name, (question, _) in FIELDS.items():
        try:
            answers[name] = input_fn(question + " ")
        except (EOFError, KeyboardInterrupt) as exc:
            raise ValueError("OWNER_INPUT_INTERRUPTED_NO_WRITE") from exc
    draft = make_draft(assessment, answers)
    for name in draft["missing_required_answers"]:
        output_fn("Missing required answer: " + name)
    output_fn("Draft only — NOT approved. No project files, WU, lease or model were created.")
    return draft


def main(argv: list[str] | None = None) -> int:
    """Only explicit complete --save-to creates a private, non-overwriting draft."""
    parser = argparse.ArgumentParser(description="Guided Create/Adopt Product Brief")
    parser.add_argument("--target", type=Path, default=Path("."))
    parser.add_argument("--repository", required=True, help="OWNER/REPO; do not infer owner identity")
    parser.add_argument("--save-to", type=Path, help="Explicitly save a NEW draft file; 0600, no overwrite")
    args = parser.parse_args(argv)
    try:
        assessment = analyze(args.target.resolve(), repository=args.repository)
        draft = collect(assessment)
        if draft["missing_required_answers"]:
            if args.save_to:
                print("REFUSED: incomplete Product Brief; nothing saved.", file=sys.stderr)
            return 2
        if args.save_to:
            save_exclusive(args.save_to, draft)
            print("Saved PRIVATE UNAPPROVED draft: " + str(args.save_to))
        else:
            print("Complete draft in this session only; nothing saved.")
            print("To explicitly save it, rerun with --save-to <new-private-json-path>.")
        print("Next: review the brief and read-only proposal; this wizard cannot approve work.")
        return 0
    except (ValueError, OSError) as exc:
        print("REFUSED: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
