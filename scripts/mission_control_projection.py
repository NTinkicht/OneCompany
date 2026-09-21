#!/usr/bin/env python3
"""Read-only Mission Control projection for Phase-1 product evidence."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

_SHA = re.compile(r"^[0-9a-f]{40}$")
_REQUIRED = ("app", "quality", "preview")


def project(revision: str, product_brief: dict, execution: dict, evidence: dict) -> dict:
    """Project trusted inputs without granting approval or execution authority."""
    if not isinstance(revision, str) or not _SHA.fullmatch(revision):
        raise ValueError("EXACT_REVISION_REQUIRED")
    if not isinstance(product_brief, dict) or product_brief.get("status") != "DRAFT":
        raise ValueError("DRAFT_PRODUCT_BRIEF_REQUIRED")
    if product_brief.get("approved") is not False:
        raise ValueError("PRODUCT_BRIEF_MUST_REMAIN_UNAPPROVED")
    if not isinstance(execution, dict) or type(execution.get("bounded")) is not bool:
        raise ValueError("TRUSTED_EXECUTION_STATE_REQUIRED")
    if not isinstance(evidence, dict):
        raise ValueError("TRUSTED_EVIDENCE_REQUIRED")

    checks = {}
    for name in _REQUIRED:
        item = evidence.get(name)
        exact = isinstance(item, dict) and item.get("revision") == revision
        passed = exact and item.get("status") == "PASS"
        checks[name] = {"exact_revision": exact, "status": "PASS" if passed else "BLOCKED"}

    ready = execution["bounded"] and all(item["status"] == "PASS" for item in checks.values())
    return {
        "schema": "onecompany.mission-control.phase1.v1",
        "revision": revision,
        "product_brief": "DRAFT_UNAPPROVED",
        "execution_core": "BOUNDED" if execution["bounded"] else "BLOCKED",
        "checks": checks,
        "readiness": "READY_FOR_OWNER_PREVIEW" if ready else "BLOCKED",
        "authority_granted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Render read-only Phase-1 Mission Control readiness")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    result = project(args.revision, data["product_brief"], data["execution"], data["evidence"])
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
