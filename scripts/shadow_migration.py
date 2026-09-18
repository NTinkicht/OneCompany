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


def _valid_actor_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and bool(item.strip()) for item in value)


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(ch in "0123456789abcdefABCDEF" for ch in value)


def _finding(code: str, message: str, *, severity: str = "blocker") -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message}


def _valid_snapshot(snapshot: dict[str, Any]) -> bool:
    observed, main_sha, source = snapshot.get("observed_at"), snapshot.get("main_sha"), snapshot.get("source")
    if not all(isinstance(value, str) and value.strip() for value in (observed, main_sha, source)) or not _sha(main_sha):
        return False
    try:
        datetime.fromisoformat(observed.replace("Z", "+00:00"))
    except ValueError:
        return False
    return snapshot.get("stale") is False and snapshot.get("derived") is False


def analyze_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    if manifest.get("schema_version") != "1.0": findings.append(_finding("SCHEMA_VERSION_UNSUPPORTED", "shadow migration manifest schema_version must equal '1.0'"))
    project = manifest.get("project") if isinstance(manifest.get("project"), dict) else {}; snapshot = manifest.get("snapshot") if isinstance(manifest.get("snapshot"), dict) else {}; live = manifest.get("live") if isinstance(manifest.get("live"), dict) else {}; legacy = manifest.get("legacy") if isinstance(manifest.get("legacy"), dict) else {}; branch_protection = manifest.get("branch_protection") if isinstance(manifest.get("branch_protection"), dict) else {}; cutover = manifest.get("cutover") if isinstance(manifest.get("cutover"), dict) else {}; proposed = manifest.get("proposed_onecompany") if isinstance(manifest.get("proposed_onecompany"), dict) else {}; evidence = manifest.get("cutover_evidence") if isinstance(manifest.get("cutover_evidence"), dict) else {}
    repository, default_branch = project.get("repository"), project.get("default_branch")
    if not isinstance(repository, str) or "/" not in repository: findings.append(_finding("PROJECT_IDENTITY_MISSING", "project.repository must be OWNER/REPO"))
    if not isinstance(default_branch, str) or not default_branch: findings.append(_finding("DEFAULT_BRANCH_MISSING", "project.default_branch is required"))
    if not _valid_snapshot(snapshot): findings.append(_finding("SNAPSHOT_PROVENANCE_INCOMPLETE", "snapshot requires valid timestamp, SHA, source, stale=false, and derived=false"))
    stream_mode = live.get("mode", "active")
    if stream_mode == "active":
        missing = [k for k in REQUIRED_LIVE_FIELDS if not ((_sha(live.get(k))) if k == "pr_head" else (isinstance(live.get(k), (str, int)) and not isinstance(live.get(k), bool) and live.get(k) != ""))]
        if missing: findings.append(_finding("LIVE_STREAM_IDENTITY_INCOMPLETE", "live stream evidence is missing or malformed: " + ", ".join(sorted(missing))))
    elif stream_mode == "idle":
        idle = live.get("idle") if isinstance(live.get("idle"), dict) else {}
        valid_idle = idle.get("verified") is True and type(idle.get("open_pr_count")) is int and idle.get("open_pr_count") == 0 and type(idle.get("active_work_unit_count")) is int and idle.get("active_work_unit_count") == 0 and _nonempty(idle.get("evidence_ref")) and _sha(snapshot.get("main_sha")) and idle.get("snapshot_sha") == snapshot.get("main_sha")
        if not valid_idle: findings.append(_finding("IDLE_STREAM_EVIDENCE_INCOMPLETE", "live.mode='idle' requires verified zero-work evidence bound to the exact snapshot"))
        conflicts = [k for k in REQUIRED_LIVE_FIELDS if live.get(k) not in (None, "")]
        if conflicts: findings.append(_finding("IDLE_STREAM_STATE_CONFLICT", "live.mode='idle' conflicts with active-stream identity"))
    else: findings.append(_finding("LIVE_STREAM_MODE_INVALID", "live.mode must be 'active' or 'idle'"))
    legacy_mode = legacy.get("mode", "active")
    if legacy_mode == "active":
        state = legacy.get("state") if isinstance(legacy.get("state"), dict) else {}; queue = legacy.get("work_queue") if isinstance(legacy.get("work_queue"), dict) else {}; registry = legacy.get("registry") if isinstance(legacy.get("registry"), dict) else {}; protocol = legacy.get("protocol") if isinstance(legacy.get("protocol"), dict) else {}
        if stream_mode == "active":
            if state.get("work_unit") in (None, "") or queue.get("work_unit") in (None, ""): findings.append(_finding("LEGACY_CACHE_INCOMPLETE", "legacy cache identity is incomplete"))
            if state.get("work_unit") != live.get("work_unit") or state.get("current_pr") != live.get("pr") or queue.get("work_unit") != live.get("work_unit"): findings.append(_finding("LIVE_CACHE_DRIFT", "legacy cache does not match live stream"))
        ra, pa = _actor_set(registry.get("active_actors")), _actor_set(protocol.get("active_actors"))
        if not ra or not pa: findings.append(_finding("ACTOR_PROVENANCE_INCOMPLETE", "both registry and protocol active-actor sets are required when legacy.mode='active'"))
        elif ra != pa: findings.append(_finding("ACTOR_PROTOCOL_DRIFT", "registry/protocol active actors disagree"))
    elif legacy_mode == "absent":
        absence = legacy.get("control_plane_absence") if isinstance(legacy.get("control_plane_absence"), dict) else {}
        if not (absence.get("verified") is True and _nonempty(absence.get("evidence_ref")) and _sha(snapshot.get("main_sha")) and absence.get("snapshot_sha") == snapshot.get("main_sha")): findings.append(_finding("LEGACY_CONTROL_PLANE_ABSENCE_UNVERIFIED", "legacy.mode='absent' requires verified absence evidence bound to exact snapshot"))
        conflict = any(key in legacy and legacy.get(key) not in (None, {}) for key in ("state", "work_queue"))
        for key in ("registry", "protocol"):
            if key in legacy:
                value = legacy.get(key)
                if not isinstance(value, dict): conflict = True
                else:
                    actors = value.get("active_actors")
                    if actors is not None and (not _valid_actor_list(actors) or bool(actors)): conflict = True
        if conflict: findings.append(_finding("LEGACY_CONTROL_PLANE_ABSENCE_CONFLICT", "legacy.mode='absent' conflicts with malformed or populated legacy evidence"))
    else: findings.append(_finding("LEGACY_CONTROL_PLANE_MODE_INVALID", "legacy.mode must be 'active' or 'absent'"))
    if branch_protection.get("verified") is not True: findings.append(_finding("BRANCH_PROTECTION_UNVERIFIED", "default-branch protection evidence is not administration-verified"))
    elif branch_protection.get("protected") is not True: findings.append(_finding("DEFAULT_BRANCH_UNPROTECTED", "verified default branch is not protected"))
    incumbents_raw = manifest.get("incumbent_writers"); incumbents = incumbents_raw if isinstance(incumbents_raw, list) else []; inventory_complete = manifest.get("incumbent_writer_inventory_complete") is True; writer_map: dict[str, list[str]] = defaultdict(list); declared: dict[str, set[str]] = defaultdict(set)
    if not inventory_complete: findings.append(_finding("INCUMBENT_WRITER_INVENTORY_INCOMPLETE", "incumbent writer inventory must be explicitly reviewed complete"))
    if not isinstance(incumbents_raw, list): findings.append(_finding("INCUMBENT_WRITER_INVENTORY_MALFORMED", "incumbent_writers must be a list"))
    elif not incumbents and manifest.get("no_active_mutation_writers_verified") is not True: findings.append(_finding("INCUMBENT_WRITER_INVENTORY_EMPTY", "empty incumbent inventory requires verification"))
    malformed = False
    for writer in incumbents:
        if not isinstance(writer, dict): malformed = True; continue
        name, caps = writer.get("name"), writer.get("capabilities")
        if not (isinstance(name, str) and name.strip() and isinstance(caps, list) and all(isinstance(c, str) and c.strip() for c in caps) and isinstance(writer.get("active"), bool) and isinstance(writer.get("mutation_capable"), bool) and isinstance(writer.get("reviewed"), bool)): malformed = True; continue
        if writer.get("mutation_capable") and not caps: findings.append(_finding("INCUMBENT_WRITER_CAPABILITIES_INCOMPLETE", f"mutation-capable incumbent {name!r} needs capabilities")); continue
        if writer.get("reviewed"): [declared[c].add(name) for c in caps]
        if writer.get("active") and writer.get("mutation_capable"): [writer_map[c].append(name) for c in caps]
    if malformed: findings.append(_finding("INCUMBENT_WRITER_INVENTORY_MALFORMED", "every incumbent writer record must be valid"))
    for cap, names in writer_map.items():
        if len(set(names)) > 1: findings.append(_finding("DUAL_WRITER_RISK", f"capability {cap!r} has multiple active writers"))
    if stream_mode == "idle" and any(isinstance(w, dict) and w.get("active") is True and w.get("mutation_capable") is True for w in incumbents): findings.append(_finding("IDLE_STREAM_WRITER_CONFLICT", "idle stream conflicts with active mutation writer"))
    ownership = cutover.get("owner_by_capability"); verified_empty = isinstance(incumbents_raw, list) and not incumbents and inventory_complete and manifest.get("no_active_mutation_writers_verified") is True
    if not isinstance(ownership, dict) or (not ownership and not verified_empty): findings.append(_finding("CUTOVER_OWNERSHIP_UNRESOLVED", "cutover ownership must be explicit"))
    elif isinstance(ownership, dict):
        for cap in writer_map:
            if ownership.get(cap) not in declared.get(cap, set()): findings.append(_finding("CUTOVER_OWNERSHIP_UNRESOLVED", f"owner for {cap!r} is unresolved"))
    if proposed.get("mode") != "shadow": findings.append(_finding("SHADOW_MODE_REQUIRED", "C2a requires shadow mode"))
    if proposed.get("mutation_capable") is not False: findings.append(_finding("SHADOW_MUTATION_FORBIDDEN", "C2a must be non-mutating"))
    blockers = manifest.get("adoption_blockers")
    if blockers is not None:
        if not isinstance(blockers, list): findings.append(_finding("ADOPTION_BLOCKERS_MALFORMED", "adoption_blockers must be a list"))
        else:
            for i, b in enumerate(blockers):
                if not isinstance(b, dict) or not _nonempty(b.get("code")) or not _nonempty(b.get("message")): findings.append(_finding("ADOPTION_BLOCKERS_MALFORMED", f"adoption_blockers[{i}] malformed"))
                else: findings.append(_finding(b["code"].strip(), b["message"].strip()))
    expected = {"active_stream_status":"confirmed","surface_classifications_reviewed":True,"rollback_verified":True,"human_decisions_resolved":True,"zero_extra_spend":True,"autonomy_level":"L1","staging_branch":"epic-0.6-integration","fresh_c2_reconciliation":True}
    missing = [k for k in REQUIRED_EVIDENCE if evidence.get(k) != expected[k]]
    if missing: findings.append(_finding("CUTOVER_EVIDENCE_INCOMPLETE", "mandatory cutover evidence incomplete: " + ", ".join(sorted(missing))))
    codes = sorted({f["code"] for f in findings if f.get("severity") == "blocker"})
    return {"repository":repository,"snapshot_sha":snapshot.get("main_sha"),"stream_mode":stream_mode,"legacy_mode":legacy_mode,"shadow_only":proposed.get("mode")=="shadow" and proposed.get("mutation_capable") is False,"target_mutated":False,"mutation_ready":not codes,"blocker_codes":codes,"findings":findings}


def load_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict): raise ValueError("manifest root must be an object")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("manifest", type=Path); args = parser.parse_args(argv)
    try: report = analyze_manifest(load_manifest(args.manifest))
    except (OSError, json.JSONDecodeError, ValueError) as exc: print(f"ERROR: {exc}", file=sys.stderr); return 2
    print(json.dumps(report, indent=2, sort_keys=True)); return 0 if report["mutation_ready"] else 1


if __name__ == "__main__": raise SystemExit(main())
