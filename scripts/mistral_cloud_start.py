#!/usr/bin/env python3
"""Owner-authorized Mistral canonical WU branch/PR intake; no lease or code claim.

The trusted GitHub Actions parent, not the model, owns GitHub credentials.
A READY LOW/MEDIUM protected-main WU with an unused literal test path is required.
After the canonical PR is opened, a separate base-trusted PR/WU binding and
a real native implementation lease are still required for MISTRAL_WORK_V1.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

from onecompany_lib import CONTROL, load_json, emergency_stop_active
from mistral_cloud_work import literal_paths

REPO = "NTinkicht/OneCompany"
SHA = re.compile(r"[a-f0-9]{40}\Z")
WU = re.compile(r"WU[0-9A-Za-z._-]{3,100}\Z")
BRANCH = re.compile(r"wu-[a-z0-9][a-z0-9-]{2,80}\Z")
MARKER = "MISTRAL_START_V1"


def assignment(body: str) -> dict[str, str]:
    if len(body) > 2000 or body.count(MARKER) != 1:
        raise ValueError("START_MARKER_INVALID")
    rows = body.strip().splitlines()
    if len(rows) != 4 or rows[:2] != ["@mistral-vibe", MARKER]:
        raise ValueError("START_FIELDS_INVALID")
    fields = {}
    for row in rows[2:]:
        name, sep, value = row.partition(": ")
        if sep != ": " or name in fields:
            raise ValueError("START_FIELDS_INVALID")
        fields[name] = value
    if set(fields) != {"work_unit", "main_sha"}:
        raise ValueError("START_FIELDS_INVALID")
    if not WU.fullmatch(fields["work_unit"]) or not SHA.fullmatch(fields["main_sha"]):
        raise ValueError("START_ID_INVALID")
    return fields


def github(path: str, *, method: str = "GET", payload: dict | None = None) -> dict:
    args = ["gh", "api", path]
    if method != "GET":
        args += ["-X", method]
    if payload is not None:
        args += ["--input", "-"]
    result = subprocess.run(args, input=json.dumps(payload) if payload is not None else None,
                            text=True, capture_output=True, timeout=25, check=False)
    if result.returncode != 0:
        raise ValueError("START_GITHUB_OPERATION_BLOCKED")
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise ValueError("START_GITHUB_RESPONSE_INVALID")
    return value


def policy_ticket(values: dict, *, queue: dict, budget: dict, config: dict,
                  actual_main_sha: str) -> dict:
    """Validate trusted snapshot and exact main before ANY mutating operation."""
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise ValueError("START_FOREIGN_REPOSITORY")
    if (not SHA.fullmatch(actual_main_sha)
            or values["main_sha"] != actual_main_sha):
        raise ValueError("START_MAIN_STALE")
    ai = budget.get("ai", {})
    if (ai.get("additional_monthly_spend_cap") != 0
            or any(ai.get(name) is not False for name in (
                "allow_paid_fallback", "allow_overage",
                "allow_auto_topup", "allow_new_paid_vendor"
            ))
            or ai.get("unknown_cost_behavior") != "forbid"):
        raise ValueError("START_FINANCIAL_POLICY_BLOCKED")
    if emergency_stop_active(config):
        raise ValueError("START_EMERGENCY_STOP")
    candidates = [w for w in queue.get("work_units", [])
                  if w.get("id") == values["work_unit"]]
    if len(candidates) != 1:
        raise ValueError("START_WU_NOT_UNIQUE")
    item = candidates[0]
    if item.get("status") != "READY" or item.get("risk_class") not in {"LOW", "MEDIUM"}:
        raise ValueError("START_NOT_READY_OR_TOO_RISKY")
    if item.get("pr") is not None:
        raise ValueError("START_WU_ALREADY_BOUND")
    branch = item.get("branch")
    if not isinstance(branch, str) or not BRANCH.fullmatch(branch):
        raise ValueError("START_BRANCH_INVALID")
    for other in queue.get("work_units", []):
        if other is not item and other.get("branch") == branch:
            raise ValueError("START_BRANCH_CONFLICT")
    done = {w["id"] for w in queue.get("work_units", [])
            if w.get("status") in {"DONE", "MERGED"} and isinstance(w.get("id"), str)}
    if not set(item.get("dependencies", [])).issubset(done):
        raise ValueError("START_DEPENDENCIES_UNVERIFIED")
    scope = literal_paths(item.get("write_scope"))
    tests = [name for name in scope if name.startswith("tests/")
             and name.endswith(".py")]
    if not tests:
        raise ValueError("START_NO_SCOPED_TEST_PATH")
    return {"work_unit": values["work_unit"], "branch": branch,
            "main_sha": actual_main_sha, "test_path": tests[0],
            "scope": list(scope)}


def prepare() -> dict:
    values = assignment(os.environ["DISPATCH_BODY"])
    live_main = github(f"repos/{REPO}/branches/main")["commit"]["sha"]
    ticket = policy_ticket(
        values, queue=load_json(CONTROL / "queue.json"),
        budget=load_json(CONTROL / "budget.json"),
        config=load_json(CONTROL / "config.json"),
        actual_main_sha=live_main,
    )
    # The absence of a branch is a hard precondition: never hijack an existing WU.
    response = subprocess.run(
        ["gh", "api", f"repos/{REPO}/git/ref/heads/{ticket['branch']}"],
        capture_output=True, text=True, timeout=20, check=False,
    )
    if response.returncode == 0:
        raise ValueError("START_BRANCH_ALREADY_EXISTS")
    if "404" not in response.stderr and "Not Found" not in response.stderr:
        raise ValueError("START_BRANCH_LOOKUP_INDETERMINATE")
    response = subprocess.run(
        ["gh", "api", f"repos/{REPO}/contents/{ticket['test_path']}?ref={live_main}"],
        capture_output=True, text=True, timeout=20, check=False,
    )
    if response.returncode == 0:
        raise ValueError("START_SCAFFOLD_ALREADY_EXISTS")
    if "404" not in response.stderr and "Not Found" not in response.stderr:
        raise ValueError("START_TEST_PATH_LOOKUP_INDETERMINATE")
    return ticket


def start(ticket: dict) -> dict:
    """Create one canonical PR with an explicitly non-model scaffold; no lease."""
    if github(f"repos/{REPO}/branches/main")["commit"]["sha"] != ticket["main_sha"]:
        raise ValueError("START_MAIN_MOVED")
    github(f"repos/{REPO}/git/refs", method="POST", payload={
        "ref": f"refs/heads/{ticket['branch']}", "sha": ticket["main_sha"],
    })
    # Source-only stub creates an actual diff. A passed CI here DOES NOT prove
    # that the Mistral model implemented or tested anything.
    content = (
        "# Canonical Mistral qualification PR bootstrap, not model-authored code.\n"
        "# A live native lease and MISTRAL_WORK_V1 must add real model-authored\n"
        "# source + regression tests before this PR can be considered done.\n"
    )
    import base64
    commit = github(
        f"repos/{REPO}/contents/{ticket['test_path']}", method="PUT",
        payload={
            "message": (
                f"chore({ticket['work_unit']}): scaffold canonical Mistral pilot PR\n\n"
                "Material-Author: onecompany-local\n"
                f"Work-Unit: {ticket['work_unit']}\n"
                "Qualification: PENDING_MODEL_CODE_AND_TEST"
            ),
            "content": base64.b64encode(content.encode()).decode(),
            "branch": ticket["branch"],
        }
    )
    head = (commit.get("commit") or {}).get("sha")
    if not isinstance(head, str) or not SHA.fullmatch(head):
        raise ValueError("START_SCAFFOLD_COMMIT_UNVERIFIED")
    pr = github(f"repos/{REPO}/pulls", method="POST", payload={
        "title": f"{ticket['work_unit']}: qualify Mistral real code and tests",
        "head": ticket["branch"],
        "base": "main",
        "draft": True,
        "body": (
            f"Canonical source-only bootstrap for {ticket['work_unit']}.\n\n"
            f"Scope: {', '.join(ticket['scope'])}.\n"
            f"Expected scaffold head: {head}.\n"
            "This draft is NOT model-authored, NOT implementation-qualified, "
            "and NOT ready to merge. A reviewed protected-main WU PR-number "
            "binding, durable Mistral implementation lease, actual model-authored "
            "source+tests, exact-head CI and independent non-Mistral final "
            "review remain required. No paid provider or GitHub token to model."
        ),
    })
    number = pr.get("number")
    if type(number) is not int or number < 1:
        raise ValueError("START_PR_IDENTITY_UNVERIFIED")
    return {"pr": number, "branch": ticket["branch"], "head": head,
            "status": "CANONICAL_DRAFT_PR_AWAITING_QUEUE_BINDING_AND_LEASE"}


def main() -> int:
    try:
        ticket = prepare()
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError,
            subprocess.TimeoutExpired):
        # This phase is read-only. Do not mistake missing eligibility for
        # a partial GitHub write or disclose remote stderr/input.
        print(json.dumps({"status": "START_BLOCKED_PREWRITE"}))
        return 2
    try:
        result = start(ticket)
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError,
            subprocess.TimeoutExpired):
        # The branch, scaffold, or even PR might already exist. Return only
        # trusted ticket coordinates and require GitHub reconciliation. A
        # second START dispatch must never attempt to "repair" this blindly.
        print(json.dumps({
            "status": "START_RECONCILE_REQUIRED",
            "work_unit": ticket["work_unit"],
            "branch": ticket["branch"],
            "main_sha": ticket["main_sha"],
        }, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
