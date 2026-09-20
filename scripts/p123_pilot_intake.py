#!/usr/bin/env python3
"""Read-only installation intake for three independently authorized pilots.

This is a preparation report, NEVER live proof of unattended execution,
source autonomy, owner consent, a native lease, or P1/P3 qualification.
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable

from a4_pr_producer import (
    GitHub, Refused, REPO, SHA, branch_for, fixture_path, preflight,
    _matching_pulls,
)
from a4_qualify import TRUSTED_CI_WORKFLOW_BLOB, TRUSTED_CI_WORKFLOW_PATH
from l2_fixture_repair import CI_BLOB, CI_PATH, REPAIR_PATH
from p123_qualify import REPAIR_SCRIPT_BLOB, REPAIR_WORKFLOW_BLOB
from onecompany_lib import ROOT

# Reviewed source hashes are Git blobs, not raw-file SHA-1 digests.
A4_PRODUCER_BLOB = "5e9d17909f533cf833a9be65e05dd0f77f74df71"
A4_PRODUCER_WORKFLOW_BLOB = "ad594a45887a209515b55d2d85cc150945070a19"
ALLOWED_KEYS = {"repository", "base_sha", "wu", "actor", "disposable"}
CONTROL = ("config", "queue", "readiness", "dispatch", "budget", "actors")
BASE_FILES = {
    "scripts/a4_pr_producer.py": A4_PRODUCER_BLOB,
    ".github/workflows/onecompany-a4-pr-producer.yml":
        A4_PRODUCER_WORKFLOW_BLOB,
    TRUSTED_CI_WORKFLOW_PATH: TRUSTED_CI_WORKFLOW_BLOB,
}
L2_FILES = {
    "scripts/l2_fixture_repair.py": REPAIR_SCRIPT_BLOB,
    REPAIR_PATH: REPAIR_WORKFLOW_BLOB,
    CI_PATH: CI_BLOB,
}
MAX_CONTROL_BYTES = 1_000_000


def blob_sha(path: Path) -> str:
    raw = path.read_bytes()
    return hashlib.sha1(
        b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw
    ).hexdigest()


def source_pins() -> dict[str, str]:
    """Require reviewed source/templates to match installed immutable pins."""
    source = {
        "scripts/a4_pr_producer.py": A4_PRODUCER_BLOB,
        "scripts/l2_fixture_repair.py": REPAIR_SCRIPT_BLOB,
        ".onecompany/templates/workflows/onecompany-a4-pr-producer.yml.disabled":
            A4_PRODUCER_WORKFLOW_BLOB,
        ".onecompany/templates/workflows/onecompany-a4-fixture-validation.yml.disabled":
            TRUSTED_CI_WORKFLOW_BLOB,
        ".onecompany/templates/workflows/onecompany-l2-fixture-repair.yml.disabled":
            REPAIR_WORKFLOW_BLOB,
        ".onecompany/templates/workflows/onecompany-l2-fixture-validation.yml.disabled":
            CI_BLOB,
    }
    for path, expected in source.items():
        try:
            if blob_sha(ROOT / path) != expected:
                raise Refused("source_pin_drift:" + path)
        except OSError:
            raise Refused("source_pin_unreadable:" + path) from None
    return source


def _entry(item: Any, *, l2: bool) -> dict:
    if not isinstance(item, dict) or set(item) != (
        ALLOWED_KEYS | ({"pr_number"} if l2 else set())
    ):
        raise Refused("pilot_manifest_keys_invalid")
    repo, base, wu, actor = (
        item[k] for k in ("repository", "base_sha", "wu", "actor")
    )
    if (not isinstance(repo, str) or not REPO.fullmatch(repo)
            or not isinstance(base, str) or not SHA.fullmatch(base)
            or not isinstance(wu, str) or fixture_path(wu) is None
            or not isinstance(actor, str) or not actor
            or len(actor) > 80 or item["disposable"] is not True):
        raise Refused("pilot_identity_or_disposable_claim_invalid")
    if l2 and (
        not isinstance(item["pr_number"], int)
        or isinstance(item["pr_number"], bool)
        or item["pr_number"] <= 0
    ):
        raise Refused("l2_existing_canonical_pr_number_required")
    return item


def _manifest(manifest: Any) -> list[tuple[str, dict]]:
    if not isinstance(manifest, dict) or set(manifest) != {
        "a4_pilots", "l2_pilot"
    }:
        raise Refused("three_pilot_manifest_required")
    a4 = manifest["a4_pilots"]
    if not isinstance(a4, list) or len(a4) != 2:
        raise Refused("two_a4_pilots_required")
    first, second = (_entry(x, l2=False) for x in a4)
    third = _entry(manifest["l2_pilot"], l2=True)
    entries = [("a4", first), ("a4", second), ("l2", third)]
    names = [x["repository"].lower() for _, x in entries]
    if len(set(names)) != 3:
        raise Refused("pilot_repositories_must_be_distinct")
    if first["repository"].split("/", 1)[0].lower() == (
        second["repository"].split("/", 1)[0].lower()
    ):
        raise Refused("a4_owners_must_be_distinct")
    return entries


def _file(api: GitHub, path: str, base: str) -> dict:
    result = api.call("GET", "/contents/" + path + "?ref=" + base)
    if not isinstance(result, dict) or result.get("type") != "file":
        raise Refused("required_target_file_missing:" + path)
    return result


def _json_file(api: GitHub, name: str, base: str) -> dict:
    path = ".onecompany/" + name + ".json"
    obj = _file(api, path, base)
    body = obj.get("content")
    if obj.get("encoding") != "base64" or not isinstance(body, str):
        raise Refused("target_control_file_unreadable:" + path)
    try:
        raw = base64.b64decode("".join(body.split()), validate=True)
        if len(raw) > MAX_CONTROL_BYTES:
            raise Refused("target_control_file_too_large:" + path)
        value = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError, base64.binascii.Error):
        raise Refused("target_control_file_unreadable:" + path) from None
    if not isinstance(value, dict):
        raise Refused("target_control_file_malformed:" + path)
    return value


def inspect(api: GitHub, item: dict, *, l2: bool) -> dict:
    """Only GET requests; live read failure never becomes an implicit pass."""
    repo, base, wu, actor = (
        item[k] for k in ("repository", "base_sha", "wu", "actor")
    )
    if api.repository != repo:
        raise Refused("repository_client_scope_mismatch")
    meta = api.call("GET", "/")
    if (not isinstance(meta, dict) or meta.get("full_name") != repo
            or meta.get("visibility") != "public"
            or meta.get("private") is not False
            or not isinstance(meta.get("default_branch"), str)):
        raise Refused("target_not_verified_public_repository")
    default = meta["default_branch"]
    ref = api.call("GET", "/git/ref/heads/" + default)
    remote = ref.get("object") if isinstance(ref, dict) else None
    if (not isinstance(remote, dict)
            or remote.get("sha") != base):
        raise Refused("target_base_not_exact_live_default_head")
    files = dict(BASE_FILES)
    if l2:
        files.update(L2_FILES)
    for path, expected in files.items():
        result = _file(api, path, base)
        if result.get("sha") != expected:
            raise Refused("reviewed_target_blob_drift:" + path)
    records = {
        key: _json_file(api, key, base)
        for key in CONTROL
    }
    # A declaration in the input manifest never authorizes a real project.
    # Require a corresponding base-trusted, target-local disposable fixture
    # setting; do not hard-code named customer/source repos into the product.
    if records["config"].get("project", {}).get("disposable_pilot") is not True:
        raise Refused("target_disposable_pilot_policy_missing")
    queue = copy.deepcopy(records["queue"])
    if l2:
        matches = [
            x for x in queue.get("work_units", [])
            if isinstance(x, dict) and x.get("id") == wu
        ]
        if len(matches) != 1 or matches[0].get("pr") != item["pr_number"]:
            raise Refused("l2_queue_pr_binding_missing")
        # P3's real worker applies the A4 common preflight against an
        # in-memory projection, preserving the authoritative PR binding.
        matches[0]["pr"] = None
    try:
        preflight(
            records["config"], queue, records["readiness"],
            records["dispatch"], records["budget"], records["actors"],
            repo=repo, actor=actor, wu=wu, base=base,
            actions=True, enabled=True,
        )
    except (TypeError, KeyError, AttributeError):
        raise Refused("target_policy_malformed") from None
    if l2:
        ready = [x for x in records["readiness"].get("actors", [])
                 if isinstance(x, dict) and x.get("actor_id") == actor]
        roster = [x for x in records["actors"].get("actors", [])
                  if isinstance(x, dict) and x.get("id") == actor]
        route = [x for x in records["dispatch"].get("actors", [])
                 if isinstance(x, dict) and x.get("actor_id") == actor]
        mechanism = (route[0].get("mechanisms") if len(route) == 1
                     else None)
        if (len(ready) != 1 or len(roster) != 1
                or "ci_remediation" not in ready[0].get(
                    "verified_capabilities", [])
                or "ci_remediation" not in roster[0].get(
                    "capabilities", [])
                or "ci_remediation" in ready[0].get(
                    "temporarily_unavailable_capabilities", [])
                or not isinstance(mechanism, list)
                or not any(
                    isinstance(x, dict)
                    and x.get("id") == "github-actions-l2-fixture-repair"
                    and x.get("kind") == "github_action"
                    and x.get("configured") is True
                    and x.get("unattended") is True
                    and isinstance(x.get("capabilities"), list)
                    and "ci_remediation" in x["capabilities"]
                    for x in mechanism
                )):
            raise Refused("l2_remediation_route_unverified")
        ledger = _json_file(api, "ledger", base)
        if (ledger.get("enabled") is not True
                or not isinstance(ledger.get("issue_number"), int)
                or isinstance(ledger["issue_number"], bool)
                or ledger["issue_number"] <= 0):
            raise Refused("l2_durable_ledger_not_configured")
        pr = api.call("GET", "/pulls/" + str(item["pr_number"]))
        head = pr.get("head") if isinstance(pr, dict) else None
        target = pr.get("base") if isinstance(pr, dict) else None
        head_repo = head.get("repo") if isinstance(head, dict) else None
        base_repo = target.get("repo") if isinstance(target, dict) else None
        if (not isinstance(head_repo, dict)
                or not isinstance(base_repo, dict)
                or pr.get("state") != "open"
                or pr.get("number") != item["pr_number"]
                or head.get("ref") != branch_for(wu)
                or not isinstance(head.get("sha"), str)
                or not SHA.fullmatch(head["sha"])
                or target.get("ref") != default
                or target.get("sha") != base
                or head_repo.get("full_name") != repo
                or base_repo.get("full_name") != repo):
            raise Refused("l2_existing_pr_identity_drift")
        claim = api.call("GET", "/git/ref/heads/" + branch_for(wu))
        live_ref = claim.get("object") if isinstance(claim, dict) else None
        if (not isinstance(live_ref, dict)
                or live_ref.get("sha") != head["sha"]):
            raise Refused("l2_existing_branch_pr_head_drift")
        phase = "L2_SOURCE_PREPARED_LEASE_CI_REVIEW_MERGE_PROOF_PENDING"
    else:
        branch = branch_for(wu)
        found = _matching_pulls(api, branch)
        if len(found) > 1:
            raise Refused("a4_duplicate_pr_inventory")
        phase = ("A4_EXISTING_STREAM_NEEDS_LIVE_QUALIFICATION" if found
                 else "A4_SOURCE_PREPARED_DISPATCH_AND_RUN_PROOF_PENDING")
    return {
        "repository": repo, "work_unit": wu, "base_sha": base,
        "phase": phase,
        "scope": "read_only_source_and_target_preflight",
        "owner_authorization_verified": False,
        "live_run_qualified": False,
        "budget_consumed_by_this_preflight": 0,
    }


def audit(manifest: dict, token: str,
          factory: Callable[[str, str], GitHub] = GitHub) -> dict:
    source_pins()
    entries = _manifest(manifest)
    results = []
    for role, entry in entries:
        try:
            result = inspect(
                factory(entry["repository"], token), entry, l2=role == "l2",
            )
        except Refused as exc:
            # These are fixed local refusal codes/path identifiers, not
            # remote API bodies. Strip everything else before reporting.
            reason = str(exc)
            if not re.fullmatch(r"[A-Za-z0-9_./,:-]{1,230}", reason):
                reason = "unavailable"
            raise Refused("pilot_preflight_blocked:" + role + ":"
                          + entry["repository"] + ":" + reason) from None
        except (OSError, ValueError, TypeError, KeyError):
            raise Refused("pilot_preflight_blocked:" + role + ":"
                          + entry["repository"] + ":live_unavailable") from None
        results.append(result)
    return {
        "status": "THREE_PILOT_INSTALLATIONS_PRECHECKED_NOT_QUALIFIED",
        "pilots": results,
        "p1_verified": False, "p3_verified": False,
        "next": "Owner verifies target authorization/runner variables, then "
                "collect immutable real Actions and ledger proof with "
                "a4_qualify.py and p123_qualify.py.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        print("PILOT_INTAKE_REFUSED:missing_read_only_token", file=sys.stderr)
        return 2
    try:
        data = json.loads(args.manifest.read_text(encoding="utf-8"))
        outcome = audit(data, token)
    except Refused as exc:
        print("PILOT_INTAKE_REFUSED:" + str(exc), file=sys.stderr)
        return 2
    except (OSError, UnicodeError, ValueError):
        print("PILOT_INTAKE_REFUSED:manifest_unavailable", file=sys.stderr)
        return 2
    print(json.dumps(outcome, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
