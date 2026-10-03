#!/usr/bin/env python3
"""Executable shared L5 control-plane mode policy."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / ".l5" / "control-plane.json"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
L5_SCRIPT = re.compile(r"^scripts/l5_[^/]+\.py$")
L5_PYC = re.compile(r"^l5_[^/]+(?:\.[^/]+)*\.pyc$")
LIVE_SAFE_MAIN_CHANGING = frozenset({"merge_expected_head", "revert"})
REQUIRED_ACTIVATION = frozenset({
    "trust_boundary_verified",
    "api_hostile_simulation_green",
    "shadow_liveness_validated",
    "platform_enforcement_verified_on_all_repositories",
    "governance_drift_human_cleared",
})
# These are the minimum files that must exist in the certified L5 runtime.
# ACTIVE verification also pins every other top-level scripts/l5_*.py file, so
# adding a new L5 helper cannot silently escape the certification boundary.
REQUIRED_MUTATION_RUNTIME_FILES = frozenset({
    ".l5/trust-policy.json",
    "scripts/l5_control_plane.py",
    "scripts/l5_trust_boundary.py",
    "scripts/l5_activation.py",
    "scripts/l5_recovery.py",
    "scripts/l5_state_machine.py",
    "scripts/l5_write_adapter.py",
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
    if (
        not isinstance(requirements, list)
        or not all(isinstance(requirement, str) for requirement in requirements)
        or set(requirements) != REQUIRED_ACTIVATION
    ):
        raise ValueError("CONTROL_PLANE_REQUIREMENTS_INVALID")
    return value


def _git_blob_sha(content: bytes) -> str:
    """Return the Git object id for exact file bytes."""
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


def _control_repository_root() -> Path:
    """Return the credential-free OneCompany object store used for certification.

    Downstream repositories must provide a separately checked-out OneCompany
    control repository through ``L5_CONTROL_REPOSITORY_ROOT``. The override is
    a source of Git objects only: the immutable ``control_ref`` remains the
    authority, and a forged checkout cannot change the bytes addressed by that
    commit id.
    """
    override = os.environ.get("L5_CONTROL_REPOSITORY_ROOT")
    return Path(override).resolve() if override else ROOT


def _git(control_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run one bounded read-only Git object query without replacement objects.

    The certification lookup must not inherit caller-controlled Git repository
    redirection (``GIT_DIR``, alternate object directories, replacement refs,
    config injection, and similar state). Keep only the process-discovery
    environment needed to launch Git and explicitly disable replacement refs.
    """
    clean_env: dict[str, str] = {}
    for name in ("PATH", "SYSTEMROOT", "WINDIR", "PATHEXT"):
        value = os.environ.get(name)
        if value:
            clean_env[name] = value
    clean_env["GIT_NO_REPLACE_OBJECTS"] = "1"
    clean_env["GIT_CONFIG_NOSYSTEM"] = "1"
    clean_env["GIT_CONFIG_GLOBAL"] = os.devnull
    return subprocess.run(
        ["git", "--no-replace-objects", "-C", str(control_root), *args],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
        env=clean_env,
    )


def _certified_runtime_blob_map(control_ref: str) -> tuple[dict[str, str] | None, str]:
    """Resolve the certified L5 file set directly from ``control_ref``.

    Expected blob identities are never accepted from the candidate manifest.
    The complete top-level ``scripts/l5_*.py`` namespace plus the trust policy
    is derived from the immutable Git tree named by ``control_ref``.
    """
    if not SHA40.fullmatch(control_ref):
        return None, "CONTROL_PLANE_REF_NOT_PINNED"
    control_root = _control_repository_root()
    try:
        commit = _git(control_root, "cat-file", "-e", f"{control_ref}^{{commit}}")
        if commit.returncode != 0:
            return None, "CONTROL_PLANE_CERTIFIED_REF_UNAVAILABLE"
        tree = _git(
            control_root,
            "ls-tree",
            "-r",
            control_ref,
            "--",
            "scripts",
            ".l5/trust-policy.json",
        )
    except (OSError, subprocess.SubprocessError):
        return None, "CONTROL_PLANE_CERTIFIED_REF_UNAVAILABLE"
    if tree.returncode != 0:
        return None, "CONTROL_PLANE_CERTIFIED_REF_UNAVAILABLE"

    blobs: dict[str, str] = {}
    try:
        for line in tree.stdout.splitlines():
            metadata, path = line.split("\t", 1)
            mode, object_type, blob_sha = metadata.split(" ", 2)
            if path != ".l5/trust-policy.json" and not L5_SCRIPT.fullmatch(path):
                continue
            if object_type != "blob" or mode not in {"100644", "100755"} or not SHA40.fullmatch(blob_sha):
                return None, "CONTROL_PLANE_CERTIFIED_RUNTIME_INVALID"
            if path in blobs:
                return None, "CONTROL_PLANE_CERTIFIED_RUNTIME_INVALID"
            blobs[path] = blob_sha
    except ValueError:
        return None, "CONTROL_PLANE_CERTIFIED_RUNTIME_INVALID"

    if not REQUIRED_MUTATION_RUNTIME_FILES.issubset(blobs):
        return None, "CONTROL_PLANE_CERTIFIED_RUNTIME_INCOMPLETE"
    return blobs, "CONTROL_PLANE_CERTIFIED_RUNTIME_RESOLVED"


def _runtime_import_artifacts_safe() -> tuple[bool, str]:
    """Reject alternate L5 bytecode import artifacts before ACTIVE mutation.

    Production entrypoints set ``sys.dont_write_bytecode`` before importing L5
    modules. Any pre-existing L5 ``.pyc`` can therefore only be stale or
    externally supplied and is rejected. A redirected pycache prefix is also
    rejected because it would hide bytecode outside the certified checkout.
    """
    if sys.pycache_prefix is not None:
        return False, "CONTROL_PLANE_RUNTIME_PYCACHE_PREFIX_SET"
    scripts = ROOT / "scripts"
    candidates = [scripts]
    cache = scripts / "__pycache__"
    try:
        if cache.exists():
            if cache.is_symlink() or not cache.is_dir():
                return False, "CONTROL_PLANE_RUNTIME_BYTECODE_INVALID"
            candidates.append(cache)
        for directory in candidates:
            for path in directory.iterdir():
                if not L5_PYC.fullmatch(path.name):
                    continue
                if path.is_symlink() or path.is_file():
                    return False, "CONTROL_PLANE_RUNTIME_BYTECODE_PRESENT"
                return False, "CONTROL_PLANE_RUNTIME_BYTECODE_INVALID"
    except OSError:
        return False, "CONTROL_PLANE_RUNTIME_BYTECODE_UNVERIFIABLE"
    return True, "CONTROL_PLANE_RUNTIME_BYTECODE_ABSENT"


def _local_runtime_blob_map() -> tuple[dict[str, str] | None, str]:
    """Hash the complete executing L5 namespace without following symlinks."""
    paths = [ROOT / ".l5" / "trust-policy.json"]
    scripts = ROOT / "scripts"
    try:
        paths.extend(sorted(scripts.glob("l5_*.py")))
    except OSError:
        return None, "CONTROL_PLANE_RUNTIME_SOURCE_UNAVAILABLE"

    blobs: dict[str, str] = {}
    for path in paths:
        try:
            if path.is_symlink() or not path.is_file():
                return None, "CONTROL_PLANE_RUNTIME_SOURCE_INVALID"
            relative = path.relative_to(ROOT).as_posix()
            if relative != ".l5/trust-policy.json" and not L5_SCRIPT.fullmatch(relative):
                return None, "CONTROL_PLANE_RUNTIME_SOURCE_INVALID"
            blobs[relative] = _git_blob_sha(path.read_bytes())
        except (OSError, ValueError):
            return None, "CONTROL_PLANE_RUNTIME_SOURCE_UNAVAILABLE"

    if not REQUIRED_MUTATION_RUNTIME_FILES.issubset(blobs):
        return None, "CONTROL_PLANE_RUNTIME_SOURCE_INCOMPLETE"
    return blobs, "CONTROL_PLANE_RUNTIME_SOURCE_RESOLVED"


def _runtime_source_verified(value: Mapping[str, Any]) -> tuple[bool, str]:
    """Bind ACTIVE authorization to the exact Git tree at ``control_ref``."""
    control_ref = value.get("control_ref")
    if not isinstance(control_ref, str) or not SHA40.fullmatch(control_ref):
        return False, "CONTROL_PLANE_REF_NOT_PINNED"
    imports_ok, imports_reason = _runtime_import_artifacts_safe()
    if not imports_ok:
        return False, imports_reason
    certified, reason = _certified_runtime_blob_map(control_ref)
    if certified is None:
        return False, reason
    local, reason = _local_runtime_blob_map()
    if local is None:
        return False, reason
    if set(local) != set(certified):
        return False, "CONTROL_PLANE_RUNTIME_FILE_SET_MISMATCH"
    if local != certified:
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
