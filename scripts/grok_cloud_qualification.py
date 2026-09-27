#!/usr/bin/env python3
"""Deterministically classify OneCompany's no-Codespace Grok cloud qualification.

This tool never creates provider capability. It proves the repository is still
fail-closed until live provider/GitHub evidence exists.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DISPATCH = ROOT / ".onecompany/dispatch.json"
TARGET_ACTOR = "grok-4-6-interactive"
TARGET_MECHANISM = "grok-supergrok-cloud-wake"
REPO = "NTinkicht/OneCompany"
ISSUE = 131
SHA = re.compile(r"^[0-9a-f]{40}$")
BOT_LOGIN = "onecompany-grok-worker[bot]"

REQUIRED_EVIDENCE_FIELDS = {
    "repo",
    "issue",
    "codespace_off",
    "human_prompt_required",
    "zero_additional_spend",
    "metered_api_used",
    "provider_execution_id",
    "github_publisher",
    "github_comment_url",
    "head_sha",
}


def mechanism() -> dict:
    data = json.loads(DISPATCH.read_text(encoding="utf-8"))
    for actor in data.get("actors", []):
        if actor.get("actor_id") != TARGET_ACTOR:
            continue
        for item in actor.get("mechanisms", []):
            if item.get("id") == TARGET_MECHANISM:
                return item
    raise ValueError("GROK_CLOUD_MECHANISM_MISSING")


def classify(evidence: dict | None = None) -> dict:
    item = mechanism()
    if item.get("kind") != "event_trigger" or item.get("unattended") is not True:
        raise ValueError("GROK_CLOUD_MECHANISM_CONTRACT_INVALID")

    if evidence is None:
        if item.get("configured") is not False or item.get("capabilities") != []:
            raise ValueError("UNVERIFIED_GROK_ROUTE_MUST_REMAIN_DISABLED")
        return {
            "status": "CAPACITY_BLOCKED",
            "mechanism": TARGET_MECHANISM,
            "reason": "PROVIDER_CLOUD_EXECUTION_NOT_VERIFIED",
            "configured": False,
            "capabilities": [],
            "owner_action_required": (
                "Complete provider-side Grok Bot/SuperGrok GitHub connection and "
                "produce one real Codespace-off event execution with authenticated "
                "GitHub evidence; do not export OAuth/session material or enable PAYG."
            ),
        }

    if not isinstance(evidence, dict) or set(evidence) != REQUIRED_EVIDENCE_FIELDS:
        raise ValueError("GROK_CLOUD_EVIDENCE_FIELDS_INVALID")
    if (
        evidence["repo"] != REPO
        or evidence["issue"] != ISSUE
        or evidence["codespace_off"] is not True
        or evidence["human_prompt_required"] is not False
        or evidence["zero_additional_spend"] is not True
        or evidence["metered_api_used"] is not False
        or not isinstance(evidence["provider_execution_id"], str)
        or not re.fullmatch(r"[A-Za-z0-9_.:-]{12,120}", evidence["provider_execution_id"])
        or evidence["github_publisher"] != BOT_LOGIN
        or not isinstance(evidence["github_comment_url"], str)
        or not evidence["github_comment_url"].startswith(
            f"https://github.com/{REPO}/issues/{ISSUE}#issuecomment-"
        )
        or not isinstance(evidence["head_sha"], str)
        or not SHA.fullmatch(evidence["head_sha"])
    ):
        raise ValueError("GROK_CLOUD_EVIDENCE_INVALID")

    # Structural evidence is intentionally still not enough to mutate dispatch.
    # The authenticated bridge/live verifier must independently inspect the
    # GitHub comment, current PR/SHA, CI and provider execution.
    return {
        "status": "LIVE_VERIFICATION_REQUIRED",
        "mechanism": TARGET_MECHANISM,
        "candidate_head_sha": evidence["head_sha"],
        "provider_execution_id": evidence["provider_execution_id"],
        "github_comment_url": evidence["github_comment_url"],
        "configured": False,
        "capabilities": [],
        "reason": "STRUCTURAL_EVIDENCE_CANNOT_SELF_PROMOTE_CAPABILITY",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    try:
        evidence = (
            json.loads(args.evidence.read_text(encoding="utf-8"))
            if args.evidence
            else None
        )
        result = classify(evidence)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "QUALIFICATION_BLOCKED", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
