#!/usr/bin/env python3
"""Analyze an external migration snapshot without mutating the target repository."""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

REQUIRED_LIVE_FIELDS = ("work_unit", "pr", "pr_head")
REQUIRED_EVIDENCE = (
    "active_stream_status",
    "surface_classifications_reviewed",
    "rollback_verified",
    "human_decisions_resolved",
    "zero_extra_spend",
    "autonomy_level",
    "staging_branch",
    "fresh_c2_reconciliation",
)


def _actor_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {item for item in value if isinstance(item, str) and item.strip()}


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _sha(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(ch in "0123456789abcdefABCDEF" for ch in value)
    )


def _finding(code: str, message: str, *, severity: str = "blocker") -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message}


def _valid_snapshot(snapshot: dict[str, Any]) -> bool:
    observed = snapshot.get("observed_at")
    main_sha = snapshot.get("main_sha")
    source = snapshot.get("source")
    if not all(isinstance(value, str) and value.strip() for value in (observed, main_sha, source)):
        return False
    if len(main_sha) != 40 or any(ch not in "0123456789abcdefABCDEF" for ch in main_sha):
        return False
    try:
        datetime.fromisoformat(observed.replace("Z", "+00:00"))
    except ValueError:
        return False
    return snapshot.get("stale") is False and snapshot.get("derived") is False


def analyze_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    if manifest.get("schema_version") != "1.0":
        findings.append(_finding("SCHEMA_VERSION_UNSUPPORTED", "shadow migration manifest schema_version must equal '1.0'"))

    project = manifest.get("project") if isinstance(manifest.get("project"), dict) else {}
    snapshot = manifest.get("snapshot") if isinstance(manifest.get("snapshot"), dict) else {}
    live = manifest.get("live") if isinstance(manifest.get("live"), dict) else {}
    legacy = manifest.get("legacy") if isinstance(manifest.get("legacy"), dict) else {}
    branch_protection = manifest.get("branch_protection") if isinstance(manifest.get("branch_protection"), dict) else {}
    cutover = manifest.get("cutover") if isinstance(manifest.get("cutover"), dict) else {}
    proposed = manifest.get("proposed_onecompany") if isinstance(manifest.get("proposed_onecompany"), dict) else {}
    evidence = manifest.get("cutover_evidence") if isinstance(manifest.get("cutover_evidence"), dict) else {}

    repository = project.get("repository")
    default_branch = project.get("default_branch")
    if not isinstance(repository, str) or "/" not in repository:
        findings.append(_finding("PROJECT_IDENTITY_MISSING", "project.repository must be OWNER/REPO"))
    if not isinstance(default_branch, str) or not default_branch:
        findings.append(_finding("DEFAULT_BRANCH_MISSING", "project.default_branch is required"))

    if not _valid_snapshot(snapshot):
        findings.append(_finding("SNAPSHOT_PROVENANCE_INCOMPLETE", "snapshot requires valid timestamp, SHA, source, stale=false, and derived=false"))

    stream_mode = live.get("mode", "active")
    if stream_mode == "active":
        missing_live = []
        for key in REQUIRED_LIVE_FIELDS:
            value = live.get(key)
            valid = isinstance(value, (str, int)) and not isinstance(value, bool) and value != ""
            if key == "pr_head":
                valid = _sha(value)
            if not valid:
                missing_live.append(key)
        if missing_live:
            findings.append(_finding("LIVE_STREAM_IDENTITY_INCOMPLETE", "live stream evidence is missing or malformed: " + ", ".join(sorted(missing_live))))
    elif stream_mode == "idle":
        idle = live.get("idle") if isinstance(live.get("idle"), dict) else {}
        zero_open_prs = isinstance(idle.get("open_pr_count"), int) and not isinstance(idle.get("open_pr_count"), bool) and idle.get("open_pr_count") == 0
        zero_active_wus = isinstance(idle.get("active_work_unit_count"), int) and not isinstance(idle.get("active_work_unit_count"), bool) and idle.get("active_work_unit_count") == 0
        idle_bound = _sha(snapshot.get("main_sha")) and idle.get("snapshot_sha") == snapshot.get("main_sha")
        if not (
            idle.get("verified") is True
            and zero_open_prs
            and zero_active_wus
            and _nonempty(idle.get("evidence_ref"))
            and idle_bound
        ):
            findings.append(_finding(
                "IDLE_STREAM_EVIDENCE_INCOMPLETE",
                "live.mode='idle' requires verified evidence, integer open_pr_count=0, integer active_work_unit_count=0, evidence_ref, and exact snapshot_sha binding",
            ))
    else:
        findings.append(_finding("LIVE_STREAM_MODE_INVALID", "live.mode must be 'active' or 'idle'"))

    legacy_mode = legacy.get("mode", "active")
    if legacy_mode == "active":
        legacy_state = legacy.get("state") if isinstance(legacy.get("state"), dict) else {}
        legacy_queue = legacy.get("work_queue") if isinstance(legacy.get("work_queue"), dict) else {}
        live_wu, live_pr = live.get("work_unit"), live.get("pr")
        state_wu, state_pr = legacy_state.get("work_unit"), legacy_state.get("current_pr")
        queue_wu = legacy_queue.get("work_unit")
        drift_parts: list[str] = []
        if stream_mode == "active":
            for label, value in (("legacy.state.work_unit", state_wu), ("legacy.work_queue.work_unit", queue_wu)):
                if not isinstance(value, (str, int)) or isinstance(value, bool) or value == "":
                    findings.append(_finding("LEGACY_CACHE_INCOMPLETE", f"{label} is missing or malformed"))
            if live_wu is not None and state_wu is not None and live_wu != state_wu:
                drift_parts.append(f"state work_unit={state_wu} vs live={live_wu}")
            if live_pr is not None and state_pr != live_pr:
                drift_parts.append(f"state current_pr={state_pr} vs live={live_pr}")
            if live_wu is not None and queue_wu is not None and live_wu != queue_wu:
                drift_parts.append(f"work_queue work_unit={queue_wu} vs live={live_wu}")
            if drift_parts:
                findings.append(_finding("LIVE_CACHE_DRIFT", "; ".join(drift_parts)))

        registry = legacy.get("registry") if isinstance(legacy.get("registry"), dict) else {}
        protocol = legacy.get("protocol") if isinstance(legacy.get("protocol"), dict) else {}
        registry_actors, protocol_actors = _actor_set(registry.get("active_actors")), _actor_set(protocol.get("active_actors"))
        if not registry_actors or not protocol_actors:
            findings.append(_finding("ACTOR_PROVENANCE_INCOMPLETE", "both registry and protocol active-actor sets are required when legacy.mode='active'"))
        elif registry_actors != protocol_actors:
            findings.append(_finding("ACTOR_PROTOCOL_DRIFT", f"registry/protocol active actors disagree: registry={sorted(registry_actors)} protocol={sorted(protocol_actors)}"))
    elif legacy_mode == "absent":
        absence = legacy.get("control_plane_absence") if isinstance(legacy.get("control_plane_absence"), dict) else {}
        absence_bound = _sha(snapshot.get("main_sha")) and absence.get("snapshot_sha") == snapshot.get("main_sha")
        registry = legacy.get("registry") if isinstance(legacy.get("registry"), dict) else {}
        protocol = legacy.get("protocol") if isinstance(legacy.get("protocol"), dict) else {}
        if not (
            absence.get("verified") is True
            and _nonempty(absence.get("evidence_ref"))
            and absence_bound
        ):
            findings.append(_finding(
                "LEGACY_CONTROL_PLANE_ABSENCE_UNVERIFIED",
                "legacy.mode='absent' requires verified absence evidence, evidence_ref, and exact snapshot_sha binding",
            ))
        if _actor_set(registry.get("active_actors")) or _actor_set(protocol.get("active_actors")):
            findings.append(_finding(
                "LEGACY_CONTROL_PLANE_ABSENCE_CONFLICT",
                "legacy.mode='absent' conflicts with a non-empty registry/protocol actor roster",
            ))
    else:
        findings.append(_finding("LEGACY_CONTROL_PLANE_MODE_INVALID", "legacy.mode must be 'active' or 'absent'"))

    if branch_protection.get("verified") is not True:
        findings.append(_finding("BRANCH_PROTECTION_UNVERIFIED", "default-branch protection evidence is not administration-verified"))
    elif branch_protection.get("protected") is not True:
        findings.append(_finding("DEFAULT_BRANCH_UNPROTECTED", "verified default branch is not protected"))

    writer_map: dict[str, list[str]] = defaultdict(list)
    incumbents_raw = manifest.get("incumbent_writers")
    incumbents = incumbents_raw if isinstance(incumbents_raw, list) else []
    inventory_complete = manifest.get("incumbent_writer_inventory_complete") is True
    if not inventory_complete:
        findings.append(_finding("INCUMBENT_WRITER_INVENTORY_INCOMPLETE", "incumbent writer inventory must be explicitly reviewed complete"))
    if not isinstance(incumbents_raw, list):
        findings.append(_finding("INCUMBENT_WRITER_INVENTORY_MALFORMED", "incumbent_writers must be a list"))
    elif not incumbents and manifest.get("no_active_mutation_writers_verified") is not True:
        findings.append(_finding("INCUMBENT_WRITER_INVENTORY_EMPTY", "empty incumbent inventory requires verified no-active-mutation-writers evidence"))
    declared_owners: dict[str, set[str]] = defaultdict(set)
    malformed_writer = False
    for writer in incumbents:
        if not isinstance(writer, dict):
            malformed_writer = True
            continue
        name = writer.get("name")
        capabilities = writer.get("capabilities")
        valid_record = (
            isinstance(name, str)
            and bool(name.strip())
            and isinstance(capabilities, list)
            and all(isinstance(capability, str) and capability.strip() for capability in capabilities)
            and isinstance(writer.get("active"), bool)
            and isinstance(writer.get("mutation_capable"), bool)
            and isinstance(writer.get("reviewed"), bool)
        )
        if not valid_record:
            malformed_writer = True
            continue
        if writer.get("mutation_capable") is True and not capabilities:
            findings.append(_finding(
                "INCUMBENT_WRITER_CAPABILITIES_INCOMPLETE",
                f"mutation-capable incumbent {name!r} must declare at least one explicit capability",
            ))
            continue
        if writer.get("reviewed") is True:
            for capability in capabilities:
                declared_owners[capability].add(name)
        if writer.get("active") is not True or writer.get("mutation_capable") is not True:
            continue
        for capability in capabilities:
            writer_map[capability].append(name)
    if malformed_writer:
        findings.append(_finding("INCUMBENT_WRITER_INVENTORY_MALFORMED", "every incumbent writer record must have reviewed scalar identity, boolean status, and valid capabilities"))
    for capability, names in sorted(writer_map.items()):
        unique = sorted(set(names))
        if len(unique) > 1:
            findings.append(_finding("DUAL_WRITER_RISK", f"capability {capability!r} has multiple active mutation-capable incumbents: {unique}"))

    if stream_mode == "idle":
        idle_active_mutators = sorted({
            writer.get("name")
            for writer in incumbents
            if isinstance(writer, dict)
            and writer.get("active") is True
            and writer.get("mutation_capable") is True
            and _nonempty(writer.get("name"))
        })
        if idle_active_mutators:
            findings.append(_finding(
                "IDLE_STREAM_WRITER_CONFLICT",
                "live.mode='idle' conflicts with active mutation-capable incumbents: " + ", ".join(idle_active_mutators),
            ))

    ownership = cutover.get("owner_by_capability")
    verified_empty_inventory = (
        isinstance(incumbents_raw, list)
        and not incumbents
        and inventory_complete
        and manifest.get("no_active_mutation_writers_verified") is True
    )
    if not isinstance(ownership, dict):
        findings.append(_finding("CUTOVER_OWNERSHIP_UNRESOLVED", "cutover.owner_by_capability must be an object assigning one reviewed owner per mutation capability"))
    elif not ownership and not verified_empty_inventory:
        findings.append(_finding("CUTOVER_OWNERSHIP_UNRESOLVED", "cutover.owner_by_capability must explicitly assign one reviewed owner per mutation capability; an empty map is allowed only for a verified empty incumbent-writer inventory"))
    else:
        for capability in sorted(writer_map):
            owner = ownership.get(capability)
            if not isinstance(owner, str) or not owner or owner not in declared_owners.get(capability, set()):
                findings.append(_finding("CUTOVER_OWNERSHIP_UNRESOLVED", f"owner for capability {capability!r} is missing, unknown, or unreviewed"))

    if proposed.get("mode") != "shadow":
        findings.append(_finding("SHADOW_MODE_REQUIRED", "C2a analysis requires proposed_onecompany.mode='shadow'"))
    if proposed.get("mutation_capable") is not False:
        findings.append(_finding("SHADOW_MUTATION_FORBIDDEN", "C2a proposed OneCompany projection must be explicitly non-mutating"))

    adoption_blockers = manifest.get("adoption_blockers")
    if adoption_blockers is not None:
        if not isinstance(adoption_blockers, list):
            findings.append(_finding("ADOPTION_BLOCKERS_MALFORMED", "adoption_blockers must be a list when present"))
        else:
            for index, blocker in enumerate(adoption_blockers):
                if not isinstance(blocker, dict) or not _nonempty(blocker.get("code")) or not _nonempty(blocker.get("message")):
                    findings.append(_finding("ADOPTION_BLOCKERS_MALFORMED", f"adoption_blockers[{index}] requires non-empty code and message"))
                    continue
                findings.append(_finding(blocker["code"].strip(), blocker["message"].strip()))

    expected = {
        "active_stream_status": "confirmed",
        "surface_classifications_reviewed": True,
        "rollback_verified": True,
        "human_decisions_resolved": True,
        "zero_extra_spend": True,
        "autonomy_level": "L1",
        "staging_branch": "epic-0.6-integration",
        "fresh_c2_reconciliation": True,
    }
    missing_evidence = [key for key in REQUIRED_EVIDENCE if evidence.get(key) != expected[key]]
    if missing_evidence:
        findings.append(_finding("CUTOVER_EVIDENCE_INCOMPLETE", "mandatory cutover evidence is missing or ambiguous: " + ", ".join(sorted(missing_evidence))))

    blockers = [item for item in findings if item["severity"] == "blocker"]
    return {
        "schema_version": "1.0", "repository": repository, "default_branch": default_branch,
        "snapshot": snapshot, "stream_mode": stream_mode, "legacy_mode": legacy_mode,
        "shadow_only": True, "target_mutated": False,
        "mutation_ready": len(blockers) == 0, "findings": findings,
        "blocker_codes": sorted({item["code"] for item in blockers}),
        "writer_capabilities": {key: sorted(set(value)) for key, value in sorted(writer_map.items())},
        "next_action": "C2b may be considered only after a fresh live reconciliation confirms this report remains valid" if not blockers else "resolve blockers in reviewed policy/evidence; keep target repository unchanged",
    }


def load_manifest(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("shadow migration manifest must be a JSON object")
    return value


def print_human(report: dict[str, Any]) -> None:
    print("Shadow Migration Readiness")
    print("=" * 60)
    print(f"Repository:      {report.get('repository') or 'unknown'}")
    print(f"Default branch:  {report.get('default_branch') or 'unknown'}")
    print("Target mutation: NO (analysis-only)")
    print(f"Mutation ready:  {'YES' if report['mutation_ready'] else 'NO'}")
    for item in report["findings"]:
        print(f"  - [{item['severity'].upper()}] {item['code']}: {item['message']}")
    print(f"\nNext: {report['next_action']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze an external OneCompany migration snapshot without mutating the target")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        report = analyze_manifest(load_manifest(Path(args.manifest)))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 2
    print(json.dumps(report, indent=2, sort_keys=True) if args.json else "") if args.json else print_human(report)
    return 0 if report["mutation_ready"] else 3


if __name__ == "__main__":
    sys.exit(main())
