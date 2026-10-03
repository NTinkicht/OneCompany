#!/usr/bin/env python3
"""Executable shared L5 control-plane mode policy."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / ".l5" / "control-plane.json"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
LIVE_SAFE_MAIN_CHANGING = frozenset({"merge_expected_head", "revert"})
REQUIRED_ACTIVATION = frozenset({
    "trust_boundary_verified",
    "api_hostile_simulation_green",
    "shadow_liveness_validated",
    "platform_enforcement_verified_on_all_repositories",
    "governance_drift_human_cleared",
})
PINNED_RUNTIME_FILES = (
    ".l5/trust-policy.json",
    "scripts/l5_control_plane.py",
    "scripts/l5_trust_boundary.py",
    "scripts/l5_shadow.py",
    "scripts/l5_api_hostile_sim.py",
    "scripts/l5_liveness.py",
    "scripts/l5_activation.py",
)


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
    if (
        not isinstance(requirements, list)
        or not all(isinstance(requirement, str) for requirement in requirements)
        or set(requirements) != REQUIRED_ACTIVATION
    ):
        raise ValueError("CONTROL_PLANE_REQUIREMENTS_INVALID")
    return value


def _runtime_source_verified(value: Mapping[str, Any]) -> tuple[bool, str]:
    """Bind ACTIVE authorization to the exact certified runtime bytes.

    ``control_ref`` identifies the certified OneCompany revision. The activation
    manifest additionally records SHA-256 digests derived from that revision so
    downstream repositories can verify byte-for-byte equivalence without
    requiring the OneCompany Git object to exist in their local repository.
    The digest map itself is root-governed by the trusted base policy.
    """
    digests = value.get("runtime_file_sha256")
    if not isinstance(digests, Mapping) or set(digests) != set(PINNED_RUNTIME_FILES):
        return False, "CONTROL_PLANE_RUNTIME_DIGESTS_MISSING"
    for relative_path in PINNED_RUNTIME_FILES:
        expected = digests.get(relative_path)
        if not isinstance(expected, str) or not SHA256.fullmatch(expected):
            return False, "CONTROL_PLANE_RUNTIME_DIGESTS_INVALID"
        try:
            actual = hashlib.sha256((ROOT / relative_path).read_bytes()).hexdigest()
        except OSError:
            return False, "CONTROL_PLANE_RUNTIME_SOURCE_UNAVAILABLE"
        if actual != expected:
            return False, "CONTROL_PLANE_RUNTIME_SOURCE_MISMATCH"
    return True, "CONTROL_PLANE_RUNTIME_SOURCE_VERIFIED"


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
    runtime_ok, runtime_reason = _runtime_source_verified(value)
    if not runtime_ok:
        return False, runtime_reason
    return True, "CONTROL_PLANE_ACTIVE"


if __name__ == "__main__":
    allowed, reason = mutation_policy(None)
    print(json.dumps({"mutation_allowed": allowed, "reason": reason}, sort_keys=True))
