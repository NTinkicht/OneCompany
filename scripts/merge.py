#!/usr/bin/env python3
"""Merge only an exact-head/base PR with live authority and trusted assurance."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from assurance_gate import validate_structure
from lease_lifecycle import append_coordination_event, coordination_view
from ledger_lib import ledger_enabled
from onecompany_lib import (
    CONTROL,
    ROOT,
    autonomy_number,
    command_exists,
    emergency_stop_active,
    github_repo_from_config,
    github_repo_from_remote,
    load_json,
    path_matches_any,
    run,
    save_json,
)
from planning_lib import by_id
from platform_identity import (
    authorize_current_principal,
    protected_default_branch_context,
    pull_request_material_author_actor_ids,
    require_authority,
    review_platform_identity,
)
from required_checks import evaluate_required_checks
from scope_guard import changed_files, live_pr, scope_errors
from trusted_assurance import _base_json, verify_trusted_packet

AUTOMATION_FROZEN_POLICY_FILES = {
    "config": ".onecompany/config.json",
    "governance": ".onecompany/governance.json",
    "ledger": ".onecompany/ledger.json",
}
BASE_QUEUE_PATH = ".onecompany/queue.json"


def _work_unit_for_pr(queue: dict, pr: int, active: list[dict]) -> dict | None:
    work = queue.get("work_units", [])
    direct = next((item for item in work if item.get("pr") == pr), None)
    if direct is not None:
        return direct
    lease = next((item for item in active if item.get("pr") == pr), None)
    wu_id = (lease or {}).get("work_unit")
    return by_id(work).get(str(wu_id)) if wu_id else None


def _sync_legacy(state: dict) -> None:
    streams = state.get("active_streams", [])
    if len(streams) == 1:
        stream = streams[0]
        state["current_work_unit"] = stream.get("work_unit")
        state["current_pr"] = stream.get("pr")
        state["current_pr_head"] = stream.get("head")
        state["current_material_authors"] = stream.get("material_authors", [])
        state["current_gate"] = stream.get("gate")
    else:
        state["current_work_unit"] = None
        state["current_pr"] = None
        state["current_pr_head"] = None
        state["current_material_authors"] = []
        state["current_gate"] = None


def _base_document(
    repo: str, path: str, base_sha: str
) -> tuple[dict | None, str | None]:
    value, _blob, error = _base_json(repo, path, base_sha)
    if value is None:
        return None, error or f"cannot load base-trusted {path}"
    return value, None


def _base_control_context(
    repo: str, base_sha: str
) -> tuple[dict[str, dict[str, Any]] | None, list[str]]:
    documents: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for key, path in {**AUTOMATION_FROZEN_POLICY_FILES, "queue": BASE_QUEUE_PATH}.items():
        value, error = _base_document(repo, path, base_sha)
        if value is None:
            errors.append(error or f"cannot load {path}")
        else:
            documents[key] = value
    return (documents if not errors else None), errors


def _automation_policy_drift_errors(base: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    for key, path in AUTOMATION_FROZEN_POLICY_FILES.items():
        candidate = load_json(CONTROL / path.rsplit("/", 1)[-1])
        if candidate != base[key]:
            errors.append(
                f"candidate changes {path}; automated merge must refuse control-policy "
                "self-modification and use the protected human policy-change route"
            )
    return errors


def _load_assurance_packet(
    value: str | None,
) -> tuple[dict | None, str | None, str | None]:
    if not value:
        return (
            None,
            None,
            "merge requires --assurance-packet; structural/review gates cannot "
            "substitute for artifact-backed assurance",
        )
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    try:
        resolved = path.resolve()
        resolved.relative_to(ROOT.resolve())
    except (OSError, ValueError):
        return None, None, "assurance packet must be a file inside the repository checkout"
    if not resolved.is_file():
        return None, None, f"assurance packet does not exist: {resolved.relative_to(ROOT)}"
    try:
        packet = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, None, f"cannot read assurance packet: {exc}"
    if not isinstance(packet, dict):
        return None, None, "assurance packet must be a JSON object"
    return packet, resolved.relative_to(ROOT).as_posix(), None


def _attestation_digest(attestation: dict) -> str:
    canonical = json.dumps(
        attestation,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _verify_reviewer(
    repo: str,
    pr: int,
    candidate_sha: str,
    base_sha: str,
    review_id: object,
    material_authors: set[str],
) -> tuple[dict | None, list[str]]:
    if not isinstance(review_id, int) or isinstance(review_id, bool) or review_id <= 0:
        return None, ["binding gate/attestation has no positive platform review_id"]
    identity, errors = review_platform_identity(
        repo,
        pr,
        review_id,
        candidate_sha,
        base_sha,
        allowed_states={"APPROVED"},
    )
    if identity is None:
        return None, errors
    ok, reasons = require_authority(identity, "code_review", material_authors)
    return (identity if ok else None), reasons


def _repository_from_checkout() -> tuple[str | None, str | None]:
    candidate = load_json(CONTROL / "config.json")
    configured = github_repo_from_config(candidate)
    remote = github_repo_from_remote()
    if not remote:
        return None, "cannot derive repository identity from git origin"
    if configured != remote:
        return None, (
            f"candidate repository identity {configured!r} differs from git origin {remote!r}"
        )
    return remote, None


def _platform_authors(
    repo: str,
    pr: int,
    head_sha: str,
    base_sha: str,
) -> tuple[set[str] | None, list[str]]:
    return pull_request_material_author_actor_ids(repo, pr, head_sha, base_sha)


def _final_coordination_check(
    repo: str,
    pr: int,
    approved_sha: str,
    approved_base: str,
    review_id: object,
    expected_authors: set[str],
) -> tuple[list[dict] | None, list[str]]:
    """Reconcile mutable authority immediately before the GitHub merge mutation."""
    errors: list[str] = []
    live, live_error = live_pr(repo, pr)
    if live is None:
        return None, [f"cannot re-read live PR immediately before merge: {live_error}"]
    if live.get("state") != "OPEN" or live.get("isDraft"):
        errors.append("PR ceased to be open/ready before merge")
    if live.get("headRefOid") != approved_sha:
        errors.append("PR head changed after assurance verification")
    if live.get("baseRefOid") != approved_base:
        errors.append("PR base changed after assurance verification")
    protected, protected_errors = protected_default_branch_context(
        repo,
        approved_base,
        claimed_branch=live.get("baseRefName"),
    )
    if protected is None:
        errors.extend(protected_errors)

    try:
        view = coordination_view(pr)
    except Exception as exc:
        return None, [f"cannot re-read coordination authority before merge: {exc}"]
    active = [
        item
        for item in view.get("active_leases", [])
        if item.get("role") == "implementation" and item.get("pr") == pr
    ]
    if not active:
        errors.append("implementation lease expired/transferred before merge")
    authors = set(view.get("material_authors", []))
    if authors != expected_authors:
        errors.append("material authorship changed after assurance verification")
    platform_authors, author_errors = _platform_authors(
        repo,
        pr,
        approved_sha,
        approved_base,
    )
    if platform_authors is None:
        errors.extend(author_errors)
    elif not platform_authors.issubset(authors):
        errors.append("new/unreconciled platform material author appeared before merge")

    gate = view.get("current_gate")
    if (
        not gate
        or gate.get("verdict") != "PASS — MERGE_READY"
        or gate.get("stale")
        or gate.get("sha") != approved_sha
        or gate.get("base_sha") != approved_base
        or gate.get("review_id") != review_id
        or set(gate.get("material_authors") or []) != authors
    ):
        errors.append("binding coordination gate changed or became stale before merge")

    reviewer, reviewer_errors = _verify_reviewer(
        repo,
        pr,
        approved_sha,
        approved_base,
        review_id,
        authors,
    )
    if reviewer is None:
        errors.append(
            "reviewer independence changed before merge: " + ",".join(reviewer_errors)
        )
    return (active if not errors else None), errors


def _github_pr(repo: str, pr: int) -> tuple[dict | None, str | None]:
    result = run(["gh", "api", f"repos/{repo}/pulls/{pr}"])
    if result.returncode != 0:
        return None, result.stderr.strip() or result.stdout.strip() or "cannot read GitHub PR"
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return None, f"invalid GitHub PR JSON: {exc}"
    return (value if isinstance(value, dict) else None), None


def _reconcile_merged_pr(repo: str, pr: int, actor_assertion: str | None) -> int:
    """Idempotently recover durable completion after GitHub merged but ledger publication failed."""
    if not ledger_enabled():
        print("REFUSED: durable ledger is disabled; there is no durable merge record to reconcile")
        return 2
    pr_doc, pr_error = _github_pr(repo, pr)
    if pr_doc is None:
        print(f"REFUSED: {pr_error}")
        return 2
    if not pr_doc.get("merged_at"):
        print(f"REFUSED: GitHub PR #{pr} is not merged")
        return 2
    base = pr_doc.get("base") or {}
    head = pr_doc.get("head") or {}
    base_sha = base.get("sha") if isinstance(base, dict) else None
    head_sha = head.get("sha") if isinstance(head, dict) else None
    base_ref = base.get("ref") if isinstance(base, dict) else None
    merge_sha = pr_doc.get("merge_commit_sha")
    if not all(isinstance(value, str) and value for value in (base_sha, head_sha, merge_sha)):
        print("REFUSED: merged PR lacks exact head/base/merge SHA metadata")
        return 2
    protected, protected_errors = protected_default_branch_context(
        repo,
        str(base_sha),
        claimed_branch=str(base_ref) if base_ref is not None else None,
    )
    if protected is None:
        for error in protected_errors:
            print(f"REFUSED: {error}")
        return 2
    queue, queue_error = _base_document(repo, BASE_QUEUE_PATH, str(base_sha))
    if queue is None:
        print(f"REFUSED: {queue_error}")
        return 2
    work_unit = next(
        (item for item in queue.get("work_units", []) if item.get("pr") == pr),
        None,
    )
    if work_unit is None:
        print(f"REFUSED: merged PR #{pr} is not mapped in its base-trusted queue")
        return 2
    wu_id = str(work_unit.get("id"))

    identity, identity_errors = authorize_current_principal(
        repo,
        str(base_sha),
        "merge_execution",
    )
    if identity is None:
        print(
            "REFUSED: authenticated principal cannot reconcile merge completion: "
            + ",".join(identity_errors)
        )
        return 2
    actor = str(identity.get("actor_id"))
    login = str(identity.get("login"))
    if actor_assertion and actor_assertion not in {actor, login}:
        print("REFUSED: --actor assertion does not match authenticated platform principal")
        return 2

    try:
        global_view = coordination_view()
        if wu_id in set(global_view.get("verified_merged_work_units", [])):
            print(f"MERGE RECONCILED: {wu_id} already has verified durable completion")
            return 0
        pr_view = coordination_view(pr)
        for lease in pr_view.get("active_leases", []):
            if lease.get("role") == "implementation":
                append_coordination_event(
                    "ROLE_LEASE_RELEASED",
                    str(lease.get("actor") or "system"),
                    {"lease_id": lease.get("id"), "pr": pr, "reason": "merged_reconcile"},
                )
        append_coordination_event(
            "MERGED",
            actor,
            {
                "pr": pr,
                "work_unit": wu_id,
                "approved_head": head_sha,
                "approved_base": base_sha,
                "merge_sha": merge_sha,
                "method": "reconciled",
                "platform_login": login,
                "identity_policy_provenance": identity.get("policy_provenance"),
                "recovered_after_partial_failure": True,
            },
        )
        verified = coordination_view()
    except Exception as exc:
        print(f"REFUSED: merge reconciliation publication failed: {exc}")
        return 2
    if wu_id not in set(verified.get("verified_merged_work_units", [])):
        print("REFUSED: recovered MERGED event did not become verified durable completion")
        return 2
    print(f"MERGE RECONCILED: PR #{pr} -> {wu_id} ({merge_sha})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--actor",
        help=(
            "Optional descriptive assertion only; authority is derived from the "
            "authenticated GitHub principal"
        ),
    )
    parser.add_argument(
        "--pr",
        type=int,
        required=True,
        help="Explicit GitHub PR number; merge authority is never inferred from candidate state",
    )
    parser.add_argument(
        "--method",
        choices=["merge", "squash", "rebase"],
        default="squash",
    )
    parser.add_argument(
        "--assurance-packet",
        help="repository-relative merge-ready assurance packet",
    )
    parser.add_argument(
        "--reconcile-merged",
        action="store_true",
        help="Recover an idempotent durable MERGED record after GitHub already merged the PR",
    )
    args = parser.parse_args()

    if emergency_stop_active({"safety": {"emergency_stop": False}}):
        print("REFUSED: external emergency stop is active; autonomous merge is frozen")
        return 2
    if not command_exists("gh") or run(["gh", "auth", "status"]).returncode != 0:
        print("REFUSED: authenticated gh CLI is required")
        return 2

    repo, repo_error = _repository_from_checkout()
    if repo is None:
        print(f"REFUSED: {repo_error}")
        return 2
    pr = args.pr
    if args.reconcile_merged:
        return _reconcile_merged_pr(repo, pr, args.actor)

    state = load_json(CONTROL / "state.json")
    live, live_error = live_pr(repo, pr)
    if live is None:
        print(f"REFUSED: cannot read live PR state: {live_error}")
        return 2
    live_head = live.get("headRefOid")
    live_base = live.get("baseRefOid")
    if live.get("state") != "OPEN" or live.get("isDraft"):
        print("REFUSED: PR is not open/ready")
        return 2
    if not isinstance(live_head, str) or not isinstance(live_base, str):
        print("REFUSED: live PR head/base SHA is unavailable")
        return 2

    base, base_errors = _base_control_context(repo, live_base)
    if base is None:
        for error in base_errors:
            print(f"REFUSED: {error}")
        return 2
    if github_repo_from_config(base["config"]) != repo:
        print("REFUSED: base-trusted repository identity differs from git origin")
        return 2
    protected_context, protected_errors = protected_default_branch_context(
        repo,
        live_base,
        claimed_branch=live.get("baseRefName"),
    )
    if protected_context is None:
        for error in protected_errors:
            print(f"REFUSED: {error}")
        return 2
    if (
        base["config"].get("project", {}).get("default_branch")
        != protected_context.get("default_branch")
    ):
        print("REFUSED: base-configured default branch differs from GitHub protected default branch")
        return 2

    drift = _automation_policy_drift_errors(base)
    if drift:
        for error in drift:
            print(f"REFUSED: {error}")
        return 2
    if emergency_stop_active(base["config"]):
        print("REFUSED: base-trusted emergency stop is active; autonomous merge is frozen")
        return 2

    try:
        level = autonomy_number(base["config"].get("autonomy", {}).get("level", "L0"))
    except ValueError as exc:
        print(f"REFUSED: {exc}")
        return 2
    if (
        level >= 3
        and base["ledger"].get("required_for_autonomous_merge")
        and not base["ledger"].get("enabled")
    ):
        print("REFUSED: L3+ autonomous merge requires durable ledger")
        return 2

    try:
        view = coordination_view(pr)
    except Exception as exc:
        print(f"REFUSED: cannot reconstruct PR coordination authority: {exc}")
        return 2
    active = [
        item
        for item in view.get("active_leases", [])
        if item.get("role") == "implementation" and item.get("pr") == pr
    ]
    if not active:
        print("REFUSED: PR has no canonical active unexpired implementation lease")
        return 2

    queue = base["queue"]
    work_unit_record = _work_unit_for_pr(queue, pr, active)
    if work_unit_record is None:
        print(f"REFUSED: PR #{pr} is not mapped to a base-trusted Work Unit")
        return 2

    paths, diff_error = changed_files(repo, pr)
    governance = base["governance"].get("control_plane", {})
    if paths is None:
        if governance.get("fail_closed_if_diff_unavailable", True):
            print(
                "REFUSED: cannot establish PR change set for governance check: "
                f"{diff_error}"
            )
            return 2
        paths = []
    protected_paths = sorted(
        path
        for path in paths
        if path_matches_any(path, governance.get("protected_paths", []))
    )
    absolute_human = sorted(
        path
        for path in paths
        if path_matches_any(path, governance.get("always_human_paths", []))
    )

    gate = view.get("current_gate")
    material_authors = set(view.get("material_authors", []))
    platform_authors, author_errors = _platform_authors(
        repo,
        pr,
        live_head,
        live_base,
    )
    if platform_authors is None:
        for error in author_errors:
            print(f"REFUSED: {error}")
        return 2
    if not platform_authors.issubset(material_authors):
        print("REFUSED: platform commit authors are not reconciled into durable authorship; rerun gate")
        return 2

    if (
        not gate
        or gate.get("verdict") != "PASS — MERGE_READY"
        or gate.get("stale")
    ):
        print("REFUSED: no current PASS — MERGE_READY coordination gate")
        return 2
    if gate.get("work_unit") not in {None, work_unit_record.get("id")}:
        print("REFUSED: gate Work Unit does not match PR mapping")
        return 2
    if set(gate.get("material_authors") or []) != material_authors:
        print("REFUSED: gate authorship snapshot differs from current authorship")
        return 2
    if not gate.get("evidence"):
        print("REFUSED: merge-ready gate has no durable evidence reference")
        return 2
    if gate.get("scope_verified") is not True:
        print("REFUSED: gate did not verify live PR scope")
        return 2

    approved_sha = gate.get("sha")
    approved_base = gate.get("base_sha")
    if not isinstance(approved_sha, str) or not isinstance(approved_base, str):
        print("REFUSED: gate must record approved head and base SHAs")
        return 2
    if live_head != approved_sha:
        print(f"REFUSED: expected-head mismatch; approved={approved_sha} live={live_head}")
        return 2
    if live_base != approved_base:
        print(
            "REFUSED: base drift invalidated gate; "
            f"reviewed_base={approved_base} live_base={live_base}. Rebase/update and rerun CI/review."
        )
        return 2

    reviewer_identity, reviewer_errors = _verify_reviewer(
        repo,
        pr,
        approved_sha,
        approved_base,
        gate.get("review_id"),
        material_authors,
    )
    if reviewer_identity is None:
        print(
            "REFUSED: gate reviewer is not currently platform-authorized: "
            + ",".join(reviewer_errors)
        )
        return 2
    if gate.get("reviewer_actor") not in {None, reviewer_identity.get("actor_id")}:
        print("REFUSED: gate actor does not match platform-derived reviewer identity")
        return 2
    if gate.get("reviewer_login") not in {None, reviewer_identity.get("login")}:
        print("REFUSED: gate login does not match platform-derived reviewer identity")
        return 2

    merge_identity, merge_errors = authorize_current_principal(
        repo,
        approved_base,
        "merge_execution",
    )
    if merge_identity is None:
        print(
            "REFUSED: authenticated GitHub principal lacks merge authority: "
            + ",".join(merge_errors)
        )
        return 2
    merge_actor = str(merge_identity.get("actor_id"))
    merge_login = str(merge_identity.get("login"))
    if args.actor and args.actor not in {merge_actor, merge_login}:
        print(
            f"REFUSED: descriptive --actor {args.actor!r} does not match authenticated "
            f"principal actor={merge_actor!r} login={merge_login!r}"
        )
        return 2

    if absolute_human:
        ok, reasons = require_authority(merge_identity, "root")
        if not ok:
            print(
                "REFUSED: always-human governance change requires platform root authority: "
                + ",".join(reasons)
            )
            return 2
    if protected_paths and governance.get("human_merge_required") is True:
        ok, reasons = require_authority(merge_identity, "protected_merge")
        if not ok:
            print(
                "REFUSED: protected control-plane change requires protected_merge authority: "
                + ",".join(reasons)
            )
            return 2

    cached_stream = next(
        (item for item in state.get("active_streams", []) if item.get("pr") == pr),
        None,
    )
    if state.get("open_blockers") or (
        cached_stream and cached_stream.get("open_blockers")
    ):
        print("REFUSED: cached blockers remain")
        return 2
    if state.get("human_decision_required") or (
        cached_stream and cached_stream.get("human_decision_required")
    ):
        print("REFUSED: cached human decision remains outstanding")
        return 2

    problems = scope_errors(paths, work_unit_record)
    if problems:
        for problem in problems:
            print(f"REFUSED: {problem}")
        return 2

    checks_ok, check_reasons, _ = evaluate_required_checks(
        repo,
        approved_sha,
        trusted_ref=approved_base,
    )
    if not checks_ok:
        for reason in check_reasons:
            print(f"REFUSED: {reason}")
        return 2

    packet, packet_path, packet_error = _load_assurance_packet(args.assurance_packet)
    if packet is None:
        print(f"REFUSED: {packet_error}")
        return 2
    structural_errors, structural_warnings = validate_structure(packet)
    if structural_errors:
        for error in structural_errors:
            print(f"REFUSED: assurance structure: {error}")
        return 2
    for warning in structural_warnings:
        print(f"WARN: assurance structure: {warning}")
    if packet.get("status") not in {"merge_ready", "done"}:
        print(
            "REFUSED: assurance packet status must be merge_ready/done, got "
            f"{packet.get('status')}"
        )
        return 2
    if packet.get("work_unit") != work_unit_record.get("id"):
        print("REFUSED: assurance packet Work Unit does not match PR mapping")
        return 2
    if packet.get("candidate_sha") != approved_sha:
        print("REFUSED: assurance packet candidate_sha does not equal approved exact head")
        return 2
    packet_authors = {str(value) for value in packet.get("material_authors", []) if value}
    if packet_authors != material_authors:
        print("REFUSED: assurance packet authorship differs from coordination authorship")
        return 2

    attestation, assurance_errors = verify_trusted_packet(
        packet,
        repo=repo,
        pr=pr,
        base_sha=approved_base,
    )
    if assurance_errors or not attestation or attestation.get("verdict") != "PASS":
        for error in assurance_errors:
            print(f"REFUSED: assurance evidence: {error}")
        print("REFUSED: no current base-trusted PASS assurance attestation")
        return 2
    att_review = attestation.get("review") or {}
    att_reviewer, att_review_errors = _verify_reviewer(
        repo,
        pr,
        approved_sha,
        approved_base,
        att_review.get("review_id"),
        material_authors,
    )
    if att_reviewer is None:
        print(
            "REFUSED: assurance reviewer is not platform-authorized: "
            + ",".join(att_review_errors)
        )
        return 2
    if att_review.get("reviewer_login") != att_reviewer.get("login"):
        print("REFUSED: assurance reviewer login does not match platform identity")
        return 2
    assurance_digest = _attestation_digest(attestation)

    active, final_errors = _final_coordination_check(
        repo,
        pr,
        approved_sha,
        approved_base,
        gate.get("review_id"),
        material_authors,
    )
    if active is None:
        for error in final_errors:
            print(f"REFUSED: final authority reconciliation: {error}")
        return 2

    merge = run(
        [
            "gh",
            "api",
            "--method",
            "PUT",
            f"repos/{repo}/pulls/{pr}/merge",
            "-f",
            f"sha={approved_sha}",
            "-f",
            f"merge_method={args.method}",
        ]
    )
    if merge.returncode != 0:
        print("MERGE FAILED:", merge.stderr.strip() or merge.stdout.strip())
        return 2
    payload = json.loads(merge.stdout)
    if not payload.get("merged"):
        print("MERGE REFUSED BY GITHUB:", payload.get("message"))
        return 2

    work_unit = work_unit_record.get("id")
    post_merge_error: Exception | None = None
    try:
        for lease in active:
            append_coordination_event(
                "ROLE_LEASE_RELEASED",
                str(lease.get("actor") or "system"),
                {"lease_id": lease.get("id"), "pr": pr, "reason": "merged"},
            )
        append_coordination_event(
            "MERGED",
            merge_actor,
            {
                "pr": pr,
                "work_unit": work_unit,
                "approved_head": approved_sha,
                "approved_base": approved_base,
                "merge_sha": payload.get("sha"),
                "method": args.method,
                "platform_login": merge_login,
                "identity_policy_provenance": merge_identity.get("policy_provenance"),
                "assurance_packet": packet_path,
                "assurance_attestation_sha256": assurance_digest,
                "assurance_policy_revision": attestation.get("policy_revision"),
            },
        )
    except Exception as exc:
        post_merge_error = exc

    now = dt.datetime.now(dt.timezone.utc).isoformat()
    state["active_leases"] = [
        lease for lease in state.get("active_leases", []) if lease.get("pr") != pr
    ]
    state["active_streams"] = [
        item for item in state.get("active_streams", []) if item.get("pr") != pr
    ]
    state["last_merge"] = {
        "pr": pr,
        "work_unit": work_unit,
        "approved_head": approved_sha,
        "approved_base": approved_base,
        "merge_sha": payload.get("sha"),
        "actor": merge_actor,
        "platform_login": merge_login,
        "identity_policy_provenance": merge_identity.get("policy_provenance"),
        "method": args.method,
        "assurance_packet": packet_path,
        "assurance_attestation_sha256": assurance_digest,
        "assurance_policy_revision": attestation.get("policy_revision"),
        "merged_at": now,
        "coordination_recovery_required": post_merge_error is not None,
    }
    state["generated_or_reconciled_at"] = now
    _sync_legacy(state)
    active_streams = state.get("active_streams", [])
    if len(active_streams) > 1:
        state["company_state"] = "ACTIVE_PARALLEL_IMPLEMENTATION"
    elif active_streams:
        state["company_state"] = "ACTIVE_IMPLEMENTATION"
    else:
        state["company_state"] = "POST_MERGE_RECONCILE"
    save_json(CONTROL / "state.json", state)

    if post_merge_error is not None:
        print(
            "MERGE SUCCEEDED BUT DURABLE COORDINATION FAILED: "
            f"{post_merge_error}. Run: python onecompany.py merge --pr {pr} "
            "--reconcile-merged"
        )
        return 3

    print(
        f"MERGED PR #{pr}: {payload.get('sha')} (approved head {approved_sha}, "
        f"base {approved_base}, principal {merge_login}/{merge_actor}, assurance {assurance_digest})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
