#!/usr/bin/env python3
"""Executable shared L5 control-plane mode policy."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / ".l5" / "control-plane.json"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
LIVE_SAFE_MAIN_CHANGING = frozenset({"merge_expected_head", "revert"})
REQUIRED_ACTIVATION = frozenset({
    "trust_boundary_verified",
    "api_hostile_simulation_green",
    "shadow_liveness_validated",
    "platform_enforcement_verified_on_all_repositories",
    "governance_drift_human_cleared",
})


def _manifest_path(path: Path | None = None) -> Path:
    """Resolve an explicit manifest or the test/operator override."""
    if path is not None:
        return path
    override = os.environ.get("L5_CONTROL_PLANE_MANIFEST")
    return Path(override) if override else MANIFEST


def load_manifest(path: Path | None = None) -> Mapping[str, Any]:
    """Load and validate the shared control-plane manifest."""
    try:
        value = json.loads(_manifest_path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("CONTROL_PLANE_UNAVAILABLE") from exc
    if not isinstance(value, Mapping) or value.get("schema_version") != "1.0":
        raise ValueError("CONTROL_PLANE_INVALID")
    if value.get("control_repository") != "NTinkicht/OneCompany":
        raise ValueError("CONTROL_PLANE_REPOSITORY_INVALID")
    requirements = value.get("activation_requirements")
    if not isinstance(requirements, list) or set(requirements) != REQUIRED_ACTIVATION:
        raise ValueError("CONTROL_PLANE_REQUIREMENTS_INVALID")
    return value


def mutation_policy(operation: str | None, path: Path | None = None) -> tuple[bool, str]:
    """Authorize one operation under SHADOW, LIVE_SAFE, or ACTIVE mode."""
    try:
        value = load_manifest(path)
    except ValueError as exc:
        return False, str(exc)

    mode = value.get("execution_mode")
    if mode == "LIVE_SAFE":
        if value.get("mutation_allowed") is not True:
            return False, "CONTROL_PLANE_MUTATIONS_DISABLED"
        if value.get("platform_enforcement") != "DEFERRED_FOR_VALIDATION":
            return False, "CONTROL_PLANE_LIVE_SAFE_INVALID"
        if operation in LIVE_SAFE_MAIN_CHANGING:
            return False, "CONTROL_PLANE_LIVE_SAFE_MAIN_CHANGE_BLOCKED"
        return True, "CONTROL_PLANE_LIVE_SAFE"

    if mode != "ACTIVE":
        return False, "CONTROL_PLANE_SHADOW"
    if value.get("mutation_allowed") is not True:
        return False, "CONTROL_PLANE_MUTATIONS_DISABLED"
    if value.get("platform_enforcement") != "VERIFIED":
        return False, "PLATFORM_ENFORCEMENT_NOT_VERIFIED"
    control_ref = value.get("control_ref")
    if not isinstance(control_ref, str) or not SHA40.fullmatch(control_ref):
        return False, "CONTROL_PLANE_REF_NOT_PINNED"
    evidence = value.get("activation_evidence")
    if not isinstance(evidence, Mapping):
        return False, "ACTIVATION_EVIDENCE_MISSING"
    if any(evidence.get(name) is not True for name in REQUIRED_ACTIVATION):
        return False, "ACTIVATION_EVIDENCE_INCOMPLETE"
    return True, "CONTROL_PLANE_ACTIVE"


if __name__ == "__main__":
    allowed, reason = mutation_policy(None)
    print(json.dumps({"mutation_allowed": allowed, "reason": reason}, sort_keys=True))
