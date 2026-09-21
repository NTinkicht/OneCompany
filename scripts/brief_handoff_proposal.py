#!/usr/bin/env python3
"""Read-only owner Product Brief → candidate Execution Core planning handoff.

This is a proposal, never a live lease, approval, RunKey or verified GitHub ref.
The trusted parent must independently reconcile exact refs, approval, planning
catalog, budget, capabilities and lease before any executable work unit exists.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{40}\Z")
REQUIRED = ("audience", "problem", "outcome", "first_feature")
KNOWN_ASSETS = ("known_stack", "existing_tests", "existing_ci", "known_contracts")


def propose(brief: dict, head: str, base: str) -> dict:
    """Preserve owner intent and discovered assets without promoting authority."""
    if not isinstance(brief, dict) or brief.get("document_kind") != "product_brief_draft":
        raise ValueError("PRODUCT_BRIEF_DRAFT_REQUIRED")
    if brief.get("status") != "DRAFT_NOT_APPROVED":
        raise ValueError("PRODUCT_BRIEF_DRAFT_REQUIRED")
    if brief.get("approval") != {"product_brief": False, "implementation": False, "deployment": False}:
        raise ValueError("DRAFT_APPROVAL_MUST_BE_FALSE")
    if brief.get("write_lease_granted") is not False or brief.get("qualified_implementer_selected") is not False:
        raise ValueError("DRAFT_AUTHORITY_MUST_BE_FALSE")
    if not isinstance(brief.get("acceptance_criteria"), list) or brief["acceptance_criteria"]:
        raise ValueError("AC_MUST_BE_PROPOSED_BY_TRUSTED_PLANNING")
    if not isinstance(brief.get("safety_blockers"), list) or brief["safety_blockers"]:
        raise ValueError("DISCOVERY_SAFETY_BLOCKED")
    if not isinstance(brief.get("missing_required_answers"), list) or brief["missing_required_answers"]:
        raise ValueError("REQUIRED_OWNER_ANSWERS_MISSING")
    answers = brief.get("answers")
    if not isinstance(answers, dict) or any(
        not isinstance(answers.get(k), str) or not answers[k].strip() for k in REQUIRED
    ):
        raise ValueError("REQUIRED_OWNER_ANSWERS_MISSING")
    project = brief.get("project")
    if not isinstance(project, dict) or project.get("path") not in ("create", "adopt"):
        raise ValueError("CREATE_OR_ADOPT_REQUIRED")
    if not isinstance(project.get("repository"), str) or not project["repository"]:
        raise ValueError("REPOSITORY_REQUIRED")
    if any(not isinstance(project.get(k), list) or any(not isinstance(v, str) for v in project[k]) for k in KNOWN_ASSETS):
        raise ValueError("KNOWN_ASSETS_INVALID")
    if not isinstance(head, str) or not isinstance(base, str) or not SHA.fullmatch(head) or not SHA.fullmatch(base) or head == base:
        raise ValueError("EXACT_DISTINCT_REVISIONS_REQUIRED")
    return {
        "schema": "onecompany.phase1-brief-handoff-proposal.v1",
        "read_only": True,
        "authorization": "NOT_GRANTED",
        "state": "AWAIT_TRUSTED_PLANNING_AND_OWNER_APPROVAL",
        "source_refs_unverified": {"head": head, "base": base},
        "run_key": None,
        "lease_id": None,
        "canonical_work_unit": None,
        "project": {k: project.get(k) for k in ("name", "repository", "default_branch", "path", *KNOWN_ASSETS)},
        "owner_intent": {k: answers[k].strip() for k in REQUIRED},
        "constraints": answers.get("constraints"),
        "acceptance_criteria": [],
        "next_action": "Trusted parent: verify live refs and owner authorization; propose acceptance criteria and one canonical WU in existing planning/Execution Core.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only candidate brief handoff; never grants approval")
    parser.add_argument("--brief", required=True, type=Path)
    parser.add_argument("--head", required=True)
    parser.add_argument("--base", required=True)
    args = parser.parse_args(argv)
    if not args.brief.is_file():
        parser.error("bounded saved Product Brief required")
    try:
        with args.brief.open("rb") as source:
            raw_brief = source.read(16_385)
        if len(raw_brief) > 16_384:
            parser.error("bounded saved Product Brief required")
        candidate = propose(json.loads(raw_brief), args.head, args.base)
    except (OSError, ValueError, TypeError, UnicodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(candidate, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
