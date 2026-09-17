#!/usr/bin/env python3
"""Analyze an external migration snapshot without mutating the target repository."""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REQUIRED_SNAPSHOT_FIELDS = ("observed_at", "main_sha", "source")
REQUIRED_LIVE_FIELDS = ("work_unit", "pr", "pr_head")


def _actor_set(value: Any) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {str(item) for item in value if isinstance(item, str) and item.strip()}


def _finding(code: str, message: str, *, severity: str = "blocker") -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message}


def analyze_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return deterministic cutover-readiness findings for one external snapshot."""
    findings: list[dict[str, str]] = []

    project = manifest.get("project") if isinstance(manifest.get("project"), dict) else {}
    snapshot = manifest.get("snapshot") if isinstance(manifest.get("snapshot"), dict) else {}
    live = manifest.get("live") if isinstance(manifest.get("live"), dict) else {}
    legacy = manifest.get("legacy") if isinstance(manifest.get("legacy"), dict) else {}
    branch_protection = (
        manifest.get("branch_protection")
        if isinstance(manifest.get("branch_protection"), dict)
        else {}
    )
    cutover = manifest.get("cutover") if isinstance(manifest.get("cutover"), dict) else {}
    proposed = (
        manifest.get("proposed_onecompany")
        if isinstance(manifest.get("proposed_onecompany"), dict)
        else {}
    )

    repository = project.get("repository")
    default_branch = project.get("default_branch")
    if not isinstance(repository, str) or "/" not in repository:
        findings.append(_finding("PROJECT_IDENTITY_MISSING", "project.repository must be OWNER/REPO"))
    if not isinstance(default_branch, str) or not default_branch:
        findings.append(_finding("DEFAULT_BRANCH_MISSING", "project.default_branch is required"))

    missing_snapshot = [key for key in REQUIRED_SNAPSHOT_FIELDS if not snapshot.get(key)]
    if missing_snapshot:
        findings.append(
            _finding(
                "SNAPSHOT_PROVENANCE_INCOMPLETE",
                "snapshot provenance is missing: " + ", ".join(sorted(missing_snapshot)),
            )
        )

    missing_live = [key for key in REQUIRED_LIVE_FIELDS if live.get(key) in {None, ""}]
    if missing_live:
        findings.append(
            _finding(
                "LIVE_STREAM_IDENTITY_INCOMPLETE",
                "live stream evidence is missing: " + ", ".join(sorted(missing_live)),
            )
        )

    legacy_state = legacy.get("state") if isinstance(legacy.get("state"), dict) else {}
    legacy_queue = legacy.get("work_queue") if isinstance(legacy.get("work_queue"), dict) else {}
    live_wu = live.get("work_unit")
    live_pr = live.get("pr")
    state_wu = legacy_state.get("work_unit")
    state_pr = legacy_state.get("current_pr")
    queue_wu = legacy_queue.get("work_unit")

    drift_parts: list[str] = []
    if live_wu and state_wu and live_wu != state_wu:
        drift_parts.append(f"state work_unit={state_wu} vs live={live_wu}")
    if live_pr is not None and state_pr != live_pr:
        drift_parts.append(f"state current_pr={state_pr} vs live={live_pr}")
    if live_wu and queue_wu and live_wu != queue_wu:
        drift_parts.append(f"work_queue work_unit={queue_wu} vs live={live_wu}")
    if drift_parts:
        findings.append(_finding("LIVE_CACHE_DRIFT", "; ".join(drift_parts)))

    registry = legacy.get("registry") if isinstance(legacy.get("registry"), dict) else {}
    protocol = legacy.get("protocol") if isinstance(legacy.get("protocol"), dict) else {}
    registry_actors = _actor_set(registry.get("active_actors"))
    protocol_actors = _actor_set(protocol.get("active_actors"))
    if not registry_actors or not protocol_actors:
        findings.append(
            _finding(
                "ACTOR_PROVENANCE_INCOMPLETE",
                "both registry and protocol active-actor sets are required",
            )
        )
    elif registry_actors != protocol_actors:
        findings.append(
            _finding(
                "ACTOR_PROTOCOL_DRIFT",
                "registry/protocol active actors disagree: "
                f"registry={sorted(registry_actors)} protocol={sorted(protocol_actors)}",
            )
        )

    if branch_protection.get("verified") is not True:
        findings.append(
            _finding(
                "BRANCH_PROTECTION_UNVERIFIED",
                "default-branch protection evidence is not administration-verified",
            )
        )
    elif branch_protection.get("protected") is not True:
        findings.append(
            _finding(
                "DEFAULT_BRANCH_UNPROTECTED",
                "verified default branch is not protected",
            )
        )

    writer_map: dict[str, list[str]] = defaultdict(list)
    incumbents = manifest.get("incumbent_writers")
    if not isinstance(incumbents, list):
        incumbents = []
    for writer in incumbents:
        if not isinstance(writer, dict):
            continue
        if writer.get("active") is not True or writer.get("mutation_capable") is not True:
            continue
        name = writer.get("name")
        if not isinstance(name, str) or not name:
            continue
        capabilities = writer.get("capabilities")
        if not isinstance(capabilities, list):
            continue
        for capability in capabilities:
            if isinstance(capability, str) and capability:
                writer_map[capability].append(name)

    for capability, names in sorted(writer_map.items()):
        unique = sorted(set(names))
        if len(unique) > 1:
            findings.append(
                _finding(
                    "DUAL_WRITER_RISK",
                    f"capability {capability!r} has multiple active mutation-capable incumbents: {unique}",
                )
            )

    ownership = cutover.get("owner_by_capability")
    if not isinstance(ownership, dict) or not ownership:
        findings.append(
            _finding(
                "CUTOVER_OWNERSHIP_UNRESOLVED",
                "cutover.owner_by_capability must explicitly assign one owner per mutation capability",
            )
        )
    else:
        for capability in sorted(writer_map):
            owner = ownership.get(capability)
            if not isinstance(owner, str) or not owner:
                findings.append(
                    _finding(
                        "CUTOVER_OWNERSHIP_UNRESOLVED",
                        f"no cutover owner is assigned for capability {capability!r}",
                    )
                )

    if proposed.get("mode") != "shadow":
        findings.append(
            _finding(
                "SHADOW_MODE_REQUIRED",
                "C2a analysis requires proposed_onecompany.mode='shadow'",
            )
        )
    if proposed.get("mutation_capable") is not False:
        findings.append(
            _finding(
                "SHADOW_MUTATION_FORBIDDEN",
                "C2a proposed OneCompany projection must be explicitly non-mutating",
            )
        )

    blockers = [item for item in findings if item["severity"] == "blocker"]
    report = {
        "schema_version": "1.0",
        "repository": repository,
        "default_branch": default_branch,
        "snapshot": snapshot,
        "shadow_only": True,
        "target_mutated": False,
        "mutation_ready": len(blockers) == 0,
        "findings": findings,
        "blocker_codes": sorted({item["code"] for item in blockers}),
        "writer_capabilities": {key: sorted(set(value)) for key, value in sorted(writer_map.items())},
        "next_action": (
            "C2b may be considered only after a fresh live reconciliation confirms this report remains valid"
            if not blockers
            else "resolve blockers in reviewed policy/evidence; keep target repository unchanged"
        ),
    }
    return report


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
    if report["findings"]:
        print("\nFindings:")
        for item in report["findings"]:
            print(f"  - [{item['severity'].upper()}] {item['code']}: {item['message']}")
    print(f"\nNext: {report['next_action']}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Analyze an external OneCompany migration snapshot without mutating the target"
    )
    parser.add_argument("--manifest", required=True, help="Path to a reviewed external snapshot manifest")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        report = analyze_manifest(load_manifest(Path(args.manifest)))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 2
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_human(report)
    return 0 if report["mutation_ready"] else 3


if __name__ == "__main__":
    sys.exit(main())
