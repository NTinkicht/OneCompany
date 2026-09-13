#!/usr/bin/env python3
"""Mechanically merge only an exact-head/base, independently approved and assured PR."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

from assurance_gate import validate_structure
from ledger_lib import derive, ledger_config, ledger_enabled, list_events, post_event
from onecompany_lib import (
    CONTROL,
    ROOT,
    always_human_paths,
    autonomy_number,
    command_exists,
    emergency_stop_active,
    github_repo_from_config,
    governance_config,
    load_json,
    protected_control_plane_paths,
    run,
    save_json,
)
from planning_lib import by_id
from platform_identity import (
    authorize_current_principal,
    require_authority,
    review_platform_identity,
)
from required_checks import evaluate_required_checks
from scope_guard import changed_files, live_pr, scope_errors
from trusted_assurance import verify_trusted_packet


def _stream_for_pr(state: dict, pr: int) -> dict | None:
    return next((stream for stream in state.get("active_streams", []) if stream.get("pr") == pr), None)


def _work_unit_for_pr(queue: dict, state: dict, pr: int) -> dict | None:
    work = queue.get("work_units", [])
    direct = next((item for item in work if item.get("pr") == pr), None)
    if direct is not None:
        return direct
    stream = _stream_for_pr(state, pr)
    wu_id = (stream or {}).get("work_unit") or state.get("current_work_unit")
    return by_id(work).get(str(wu_id)) if wu_id else None


def _default_pr(state: dict) -> int | None:
    streams = [s for s in state.get("active_streams", []) if isinstance(s.get("pr"), int)]
    if len(streams) == 1:
        return streams[0].get("pr")
    return state.get("current_pr") if len(streams) <= 1 else None


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


def _load_assurance_packet(value: str | None) -> tuple[dict | None, str | None, str | None]:
    if not value:
        return None, None, "merge requires --assurance-packet; structural/review gates cannot substitute for artifact-backed assurance"
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
        attestation, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _enrich_gate_from_events(gate: dict | None, events: list[dict], pr: int) -> dict | None:
    """Recover immutable review provenance from the append-only GATE event."""
    if not gate:
        return gate
    matches: list[dict] = []
    for event in events:
        payload = event.get("payload") or {}
        if (
            event.get("type") == "GATE"
            and payload.get("pr") == pr
            and payload.get("sha") == gate.get("sha")
            and payload.get("base_sha") == gate.get("base_sha")
            and event.get("actor") == gate.get("reviewer_actor")
        ):
            matches.append(event)
    if not matches:
        return gate
    payload = matches[-1].get("payload") or {}
    enriched = dict(gate)
    for key in ("review_id", "reviewer_login", "review_identity"):
        if key in payload:
            enriched[key] = payload.get(key)
    return enriched


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--actor",
        help="Optional descriptive assertion only; authority is derived from the authenticated GitHub principal",
    )
    parser.add_argument("--pr", type=int)
    parser.add_argument("--method", choices=["merge", "squash", "rebase"], default="squash")
    parser.add_argument("--assurance-packet", help="repository-relative merge-ready assurance packet")
    args = parser.parse_args()

    if emergency_stop_active():
        print("REFUSED: emergency stop is active; autonomous merge is frozen")
        return 2
    if not command_exists("gh") or run(["gh", "auth", "status"]).returncode != 0:
        print("REFUSED: authenticated gh CLI is required")
        return 2

    config = load_json(CONTROL / "config.json")
    state = load_json(CONTROL / "state.json")
    queue = load_json(CONTROL / "queue.json")
    repo = github_repo_from_config(config)
    pr = args.pr or _default_pr(state)
    if not repo or not pr:
        print("REFUSED: repository/explicit --pr is required when multiple streams are active")
        return 2
    try:
        level = autonomy_number(config.get("autonomy", {}).get("level", "L0"))
    except ValueError as exc:
        print(f"REFUSED: {exc}")
        return 2
    if level >= 3 and ledger_config().get("required_for_autonomous_merge") and not ledger_enabled():
        print("REFUSED: L3+ autonomous merge requires durable ledger")
        return 2

    paths, diff_error = changed_files(repo, pr)
    governance = governance_config().get("control_plane", {})
    if paths is None:
        if governance.get("fail_closed_if_diff_unavailable", True):
            print(f"REFUSED: cannot establish PR change set for governance check: {diff_error}")
            return 2
        paths = []
    protected = protected_control_plane_paths(paths)
    absolute_human = always_human_paths(paths)

    stream = _stream_for_pr(state, pr)
    work_unit_record = _work_unit_for_pr(queue, state, pr)
    if work_unit_record is None:
        print(f"REFUSED: PR #{pr} is not mapped to a versioned Work Unit")
        return 2
    gate = (stream or {}).get("gate", state.get("current_gate"))
    active = [
        lease
        for lease in state.get("active_leases", [])
        if lease.get("status") == "active"
        and lease.get("role") == "implementation"
        and lease.get("pr") == pr
    ]
    material_authors = set(
        (stream or {}).get("material_authors", state.get("current_material_authors", []))
    )
    events: list[dict] = []
    if ledger_enabled():
        try:
            events = list_events()
            view = derive(events, pr)
            gate = _enrich_gate_from_events(view.get("current_gate"), events, pr)
            active = view.get("active_leases", [])
            material_authors = set(view.get("material_authors", []))
        except Exception as exc:
            print(f"REFUSED: cannot read durable ledger: {exc}")
            return 2

    if not gate or gate.get("verdict") != "PASS — MERGE_READY" or gate.get("stale"):
        print("REFUSED: no current durable PASS — MERGE_READY gate")
        return 2
    if gate.get("work_unit") not in {None, work_unit_record.get("id")}:
        print("REFUSED: gate Work Unit does not match PR mapping")
        return 2
    if set(gate.get("material_authors") or []) != material_authors:
        print("REFUSED: gate authorship snapshot differs from current durable authorship")
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

    reviewer_identity, reviewer_errors = _verify_reviewer(
        repo,
        pr,
        approved_sha,
        approved_base,
        gate.get("review_id"),
        material_authors,
    )
    if reviewer_identity is None:
        print("REFUSED: durable gate reviewer is not currently platform-authorized: " + ",".join(reviewer_errors))
        return 2
    if gate.get("reviewer_actor") not in {None, reviewer_identity.get("actor_id")}:
        print("REFUSED: durable gate actor does not match platform-derived reviewer identity")
        return 2
    if gate.get("reviewer_login") not in {None, reviewer_identity.get("login")}:
        print("REFUSED: durable gate login does not match platform-derived reviewer identity")
        return 2

    merge_identity, merge_errors = authorize_current_principal(
        repo, approved_base, "merge_execution"
    )
    if merge_identity is None:
        print("REFUSED: authenticated GitHub principal lacks merge authority: " + ",".join(merge_errors))
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
            print("REFUSED: always-human governance change requires platform root authority: " + ",".join(reasons))
            return 2
    if protected and governance.get("human_merge_required") is True:
        ok, reasons = require_authority(merge_identity, "protected_merge")
        if not ok:
            print("REFUSED: protected control-plane change requires protected_merge authority: " + ",".join(reasons))
            return 2

    if state.get("open_blockers") or (stream and stream.get("open_blockers")):
        print("REFUSED: open blockers remain")
        return 2
    if state.get("human_decision_required") or (stream and stream.get("human_decision_required")):
        print("REFUSED: human decision remains outstanding")
        return 2
    for problem in scope_errors(paths, work_unit_record):
        print(f"REFUSED: {problem}")
        return 2

    live, live_error = live_pr(repo, pr)
    if live is None:
        print(f"REFUSED: cannot read live PR state: {live_error}")
        return 2
    live_head = live.get("headRefOid")
    live_base = live.get("baseRefOid")
    if live.get("state") != "OPEN" or live.get("isDraft"):
        print("REFUSED: PR is not open/ready")
        return 2
    if live_head != approved_sha:
        print(f"REFUSED: expected-head mismatch; approved={approved_sha} live={live_head}")
        return 2
    if live_base != approved_base:
        print(
            f"REFUSED: base drift invalidated gate; reviewed_base={approved_base} "
            f"live_base={live_base}. Rebase/update and rerun CI/review."
        )
        return 2
    checks_ok, check_reasons, _ = evaluate_required_checks(
        repo, approved_sha, trusted_ref=approved_base
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
        print(f"REFUSED: assurance packet status must be merge_ready/done, got {packet.get('status')}")
        return 2
    if packet.get("work_unit") != work_unit_record.get("id"):
        print("REFUSED: assurance packet Work Unit does not match PR mapping")
        return 2
    if packet.get("candidate_sha") != approved_sha:
        print("REFUSED: assurance packet candidate_sha does not equal approved exact head")
        return 2
    packet_authors = {str(value) for value in packet.get("material_authors", []) if value}
    if packet_authors != material_authors:
        print("REFUSED: assurance packet material-authorship snapshot differs from durable authorship")
        return 2

    attestation, assurance_errors = verify_trusted_packet(
        packet, repo=repo, pr=pr, base_sha=approved_base
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
        print("REFUSED: assurance reviewer is not platform-authorized: " + ",".join(att_review_errors))
        return 2
    if att_review.get("reviewer_login") != att_reviewer.get("login"):
        print("REFUSED: assurance reviewer login does not match platform-derived identity")
        return 2
    assurance_digest = _attestation_digest(attestation)

    merge = run(
        [
            "gh", "api", "--method", "PUT", f"repos/{repo}/pulls/{pr}/merge",
            "-f", f"sha={approved_sha}", "-f", f"merge_method={args.method}",
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
    if ledger_enabled():
        try:
            for lease in active:
                post_event(
                    "ROLE_LEASE_RELEASED",
                    str(lease.get("actor") or "system"),
                    {"lease_id": lease.get("id"), "pr": pr, "reason": "merged"},
                )
            post_event(
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
            print(f"WARN: merge succeeded but ledger post-merge record failed: {exc}")

    now = dt.datetime.now(dt.timezone.utc).isoformat()
    for lease in state.get("active_leases", []):
        if (
            lease.get("status") == "active"
            and lease.get("role") == "implementation"
            and lease.get("pr") == pr
        ):
            lease["status"] = "released"
            lease["released_at"] = now
            lease["release_reason"] = "merged"
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
    }
    _sync_legacy(state)
    state["company_state"] = (
        "ACTIVE_PARALLEL_IMPLEMENTATION"
        if len(state.get("active_streams", [])) > 1
        else ("ACTIVE_IMPLEMENTATION" if state.get("active_streams") else "POST_MERGE_RECONCILE")
    )
    save_json(CONTROL / "state.json", state)
    print(
        f"MERGED PR #{pr}: {payload.get('sha')} (approved head {approved_sha}, "
        f"base {approved_base}, principal {merge_login}/{merge_actor}, assurance {assurance_digest})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
