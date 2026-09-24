#!/usr/bin/env python3
"""Read-only owner Product Brief → candidate Execution Core planning handoff.

This is a proposal, never a live lease, approval, RunKey or verified GitHub ref.
The trusted parent must independently reconcile exact refs, approval, planning
catalog, budget, capabilities and lease before any executable work unit exists.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
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


def consume_for_planning(proposal: dict, trusted_head: str, trusted_base: str) -> dict:
    """Validate an untrusted proposal for read-only existing-core planning.

    The adapter deliberately cannot create a RunKey, lease, WU, provider call,
    budget, or approval. Exact refs must already have been reconciled by the
    trusted caller; any authority-bearing or stale proposal fails closed.
    """
    if not isinstance(proposal, dict) or proposal.get("schema") != "onecompany.phase1-brief-handoff-proposal.v1":
        raise ValueError("HANDOFF_PROPOSAL_REQUIRED")
    if proposal.get("read_only") is not True or proposal.get("authorization") != "NOT_GRANTED":
        raise ValueError("HANDOFF_MUST_BE_UNAUTHORIZED")
    if proposal.get("state") != "AWAIT_TRUSTED_PLANNING_AND_OWNER_APPROVAL":
        raise ValueError("HANDOFF_STATE_INVALID")
    if any(proposal.get(field) is not None for field in ("run_key", "lease_id", "canonical_work_unit")):
        raise ValueError("EXECUTION_AUTHORITY_PRESENT")
    refs = proposal.get("source_refs_unverified")
    if (
        not isinstance(refs, dict)
        or not SHA.fullmatch(trusted_head or "")
        or not SHA.fullmatch(trusted_base or "")
        or trusted_head == trusted_base
        or refs != {"head": trusted_head, "base": trusted_base}
    ):
        raise ValueError("STALE_OR_UNVERIFIED_REVISION")
    project = proposal.get("project")
    intent = proposal.get("owner_intent")
    if not isinstance(project, dict) or not isinstance(intent, dict):
        raise ValueError("HANDOFF_CONTENT_INVALID")
    if any(not isinstance(project.get(k), list) for k in KNOWN_ASSETS):
        raise ValueError("KNOWN_ASSETS_INVALID")
    if proposal.get("acceptance_criteria") != []:
        raise ValueError("AC_MUST_BE_PROPOSED_BY_TRUSTED_PLANNING")
    return {
        "schema": "onecompany.execution-core-planning-input.v1",
        "mode": "READ_ONLY_PROPOSAL",
        "authorization": "NOT_GRANTED",
        "source_refs": {"head": trusted_head, "base": trusted_base},
        "project": {k: project.get(k) for k in ("name", "repository", "default_branch", "path", *KNOWN_ASSETS)},
        "owner_intent": {k: intent.get(k) for k in REQUIRED},
        "constraints": proposal.get("constraints"),
        "acceptance_criteria": [],
        "run_key": None,
        "lease_id": None,
        "canonical_work_unit": None,
        "provider_invocation": False,
        "requested_extra_spend": 0,
    }


def main(argv: list[str] | None = None) -> int:
    """Parse a bounded saved draft and print its unauthorized proposal JSON."""
    parser = argparse.ArgumentParser(description="Read-only candidate brief handoff; never grants approval")
    parser.add_argument("--brief", required=True, type=Path)
    parser.add_argument("--head", required=True)
    parser.add_argument("--base", required=True)
    args = parser.parse_args(argv)
    try:
        # One regular, bounded, no-follow FD; no is_file() / open() race.
        if not hasattr(os, "O_NOFOLLOW"):
            raise ValueError("SECURE_BRIEF_READ_UNAVAILABLE")
        flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(args.brief, flags)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError("SAVED_BRIEF_FILE_REQUIRED")
            with os.fdopen(descriptor, "rb", closefd=False) as source:
                raw_brief = source.read(16_385)
        finally:
            os.close(descriptor)
        if len(raw_brief) > 16_384:
            raise ValueError("SAVED_BRIEF_TOO_LARGE")
        candidate = propose(json.loads(raw_brief), args.head, args.base)
    except (OSError, ValueError, TypeError, UnicodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(candidate, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
