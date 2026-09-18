#!/usr/bin/env python3
"""Prove a target migration is quiescent before any separately reviewed cutover."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shadow_migration import analyze_manifest, load_manifest


def _finding(code: str, message: str) -> dict[str, str]:
    return {"code": code, "severity": "blocker", "message": message}


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def _sha(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(ch in "0123456789abcdefABCDEF" for ch in value)
    )


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def analyze_cutover(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return fail-closed C2b readiness without granting mutation authority."""
    shadow = analyze_manifest(manifest)
    findings: list[dict[str, str]] = []

    if not shadow["mutation_ready"]:
        findings.append(_finding("SHADOW_READINESS_REQUIRED", "C2a shadow migration blockers must be resolved before cutover rehearsal"))

    snapshot = manifest.get("snapshot")
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    live = manifest.get("live")
    live = live if isinstance(live, dict) else {}
    cutover = manifest.get("cutover")
    cutover = cutover if isinstance(cutover, dict) else {}
    proposed = manifest.get("proposed_onecompany")
    proposed = proposed if isinstance(proposed, dict) else {}

    snapshot_time = _timestamp(snapshot.get("observed_at"))
    main_sha = snapshot.get("main_sha")
    pr_head = live.get("pr_head")

    incumbents_raw = manifest.get("incumbent_writers")
    incumbents = incumbents_raw if isinstance(incumbents_raw, list) else []
    mutation_capabilities: set[str] = set()
    active_mutators: list[str] = []
    unreviewed_mutators: list[str] = []
    quiescence_missing: list[str] = []
    quiescence_times: list[datetime] = []

    for index, writer in enumerate(incumbents):
        if not isinstance(writer, dict) or writer.get("mutation_capable") is not True:
            continue
        name = writer.get("name")
        label = name.strip() if _nonempty(name) else f"writer[{index}]"
        capabilities = writer.get("capabilities")
        if isinstance(capabilities, list):
            mutation_capabilities.update(item.strip() for item in capabilities if isinstance(item, str) and item.strip())
        if writer.get("reviewed") is not True:
            unreviewed_mutators.append(label)
        if writer.get("active") is not False:
            active_mutators.append(label)
        evidence_ref = writer.get("quiescence_evidence_ref")
        quiesced_at = _timestamp(writer.get("quiesced_at"))
        if not _nonempty(evidence_ref) or quiesced_at is None:
            quiescence_missing.append(label)
        else:
            quiescence_times.append(quiesced_at)

    if unreviewed_mutators:
        findings.append(_finding("INCUMBENT_MUTATOR_UNREVIEWED", "mutation-capable incumbent records must be individually reviewed: " + ", ".join(sorted(unreviewed_mutators))))
    if active_mutators:
        findings.append(_finding("INCUMBENT_MUTATORS_STILL_ACTIVE", "mutation-capable incumbents are not quiesced: " + ", ".join(sorted(active_mutators))))
    if quiescence_missing:
        findings.append(_finding("QUIESCENCE_EVIDENCE_INCOMPLETE", "mutation-capable incumbents require quiescence evidence and timestamp: " + ", ".join(sorted(quiescence_missing))))

    stream = cutover.get("active_stream")
    stream = stream if isinstance(stream, dict) else {}
    stream_quiesced_at = _timestamp(stream.get("quiesced_at"))
    active_writer_count = stream.get("active_writer_count")
    zero_writer_count = isinstance(active_writer_count, int) and not isinstance(active_writer_count, bool) and active_writer_count == 0
    if stream.get("status") != "quiesced" or not zero_writer_count or not _nonempty(stream.get("evidence_ref")) or stream_quiesced_at is None:
        findings.append(_finding("ACTIVE_STREAM_NOT_QUIESCENT", "cutover.active_stream must prove status=quiesced, integer active_writer_count=0, evidence_ref, and timezone-aware quiesced_at"))

    reconciled_after_quiescence = cutover.get("reconciled_after_quiescence") is True
    reconciliation_completed_at = _timestamp(cutover.get("reconciliation_completed_at"))
    reconciliation_evidence_ref = cutover.get("reconciliation_evidence_ref")
    reconciliation_bound = _sha(main_sha) and cutover.get("reconciliation_snapshot_sha") == main_sha and _sha(pr_head) and cutover.get("reconciliation_pr_head") == pr_head
    expected_quiescence_count = sum(1 for writer in incumbents if isinstance(writer, dict) and writer.get("mutation_capable") is True)
    chronology_ok = (
        snapshot_time is not None
        and reconciliation_completed_at is not None
        and _nonempty(reconciliation_evidence_ref)
        and stream_quiesced_at is not None
        and all(reconciliation_completed_at >= item for item in quiescence_times)
        and reconciliation_completed_at >= stream_quiesced_at
        and snapshot_time >= reconciliation_completed_at
    )
    if not (reconciled_after_quiescence and reconciliation_bound and chronology_ok and len(quiescence_times) == expected_quiescence_count):
        findings.append(_finding("POST_QUIESCENCE_RECONCILIATION_REQUIRED", "fresh timestamped reconciliation evidence must be bound to the exact snapshot/head and complete after every incumbent and active-stream quiescence boundary"))

    writer_identity = proposed.get("writer_identity")
    if not _nonempty(writer_identity):
        findings.append(_finding("PROPOSED_WRITER_IDENTITY_MISSING", "proposed_onecompany.writer_identity is required for cutover ownership"))
    if proposed.get("writer_reviewed") is not True or not _nonempty(proposed.get("writer_evidence_ref")):
        findings.append(_finding("PROPOSED_WRITER_UNREVIEWED", "proposed OneCompany writer requires reviewed identity/capability evidence"))

    post_ownership = cutover.get("owner_by_capability_after_cutover")
    if not isinstance(post_ownership, dict):
        post_ownership = {}
    ownership_ok = bool(mutation_capabilities) and set(post_ownership) == mutation_capabilities
    if ownership_ok and _nonempty(writer_identity):
        ownership_ok = all(post_ownership.get(capability) == writer_identity for capability in mutation_capabilities)
    if not ownership_ok:
        findings.append(_finding("POST_CUTOVER_OWNERSHIP_UNRESOLVED", "every reviewed mutation capability must map exactly once to the proposed OneCompany writer"))

    rollback = cutover.get("rollback")
    rollback = rollback if isinstance(rollback, dict) else {}
    rollback_ok = rollback.get("onecompany_disable_first") is True and rollback.get("legacy_restore_requires_human") is True and rollback.get("restore_order_reviewed") is True and _nonempty(rollback.get("evidence_ref"))
    if not rollback_ok:
        findings.append(_finding("ROLLBACK_PLAN_INCOMPLETE", "rollback must disable OneCompany first, require human legacy restore, preserve reviewed order, and cite evidence"))

    human = cutover.get("human_gate")
    human = human if isinstance(human, dict) else {}
    approved_at = _timestamp(human.get("approved_at"))
    human_ok = (
        human.get("required") is True
        and human.get("approved") is True
        and _nonempty(human.get("approval_ref"))
        and approved_at is not None
        and reconciliation_completed_at is not None
        and snapshot_time is not None
        and approved_at > reconciliation_completed_at
        and approved_at > snapshot_time
        and human.get("approved_reconciliation_evidence_ref") == reconciliation_evidence_ref
        and _sha(main_sha)
        and human.get("approved_snapshot_sha") == main_sha
        and _sha(pr_head)
        and human.get("approved_pr_head") == pr_head
    )
    if not human_ok:
        findings.append(_finding("HUMAN_CUTOVER_APPROVAL_MISSING", "cutover requires explicit human approval after reconciliation and the observed snapshot, bound to its evidence and the exact reconciled snapshot/PR head"))

    blockers = [item for item in findings if item["severity"] == "blocker"]
    ready = len(blockers) == 0
    return {
        "schema_version": "1.0", "repository": shadow.get("repository"), "default_branch": shadow.get("default_branch"),
        "shadow_mutation_ready": shadow["mutation_ready"], "shadow_blocker_codes": shadow["blocker_codes"], "cutover_ready": ready,
        "target_mutated": False, "mutation_authorized": False, "authority_effects": [], "mutation_capabilities": sorted(mutation_capabilities),
        "findings": findings, "blocker_codes": sorted({item["code"] for item in blockers}),
        "next_action": "open a separately reviewed target-specific cutover change; this readiness gate grants no mutation authority" if ready else "resolve blockers and reconcile again; keep the target repository unchanged",
    }


def print_human(report: dict[str, Any]) -> None:
    print("C2b Cutover Readiness")
    print("=" * 60)
    print(f"Repository:       {report.get('repository') or 'unknown'}")
    print(f"Default branch:   {report.get('default_branch') or 'unknown'}")
    print("Target mutation:  NO (readiness-only)")
    print("Mutation authority: NO")
    print(f"Shadow ready:     {'YES' if report['shadow_mutation_ready'] else 'NO'}")
    print(f"Cutover ready:    {'YES' if report['cutover_ready'] else 'NO'}")
    for item in report["findings"]:
        print(f"  - [{item['severity'].upper()}] {item['code']}: {item['message']}")
    print(f"\nNext: {report['next_action']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prove quiescent cutover readiness without mutating the target repository")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        report = analyze_cutover(load_manifest(Path(args.manifest)))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 2
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_human(report)
    return 0 if report["cutover_ready"] else 3


if __name__ == "__main__":
    sys.exit(main())
