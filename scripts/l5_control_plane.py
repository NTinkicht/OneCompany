#!/usr/bin/env python3
"""Executable shared L5 control-plane mode policy."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).absolute().parents[1]
MANIFEST = ROOT / ".l5" / "control-plane.json"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
L5_SCRIPT = re.compile(r"^scripts/l5_[^/]+\.py$")
L5_PYC = re.compile(r"^l5_[^/]+(?:\.[^/]+)*\.pyc$")
BOOTSTRAP_PYC = re.compile(r"^control_plane_bootstrap(?:\.[^/]+)*\.pyc$")
BOOTSTRAP_PATH = "scripts/control_plane_bootstrap.py"
LIVE_SAFE_MAIN_CHANGING = frozenset({"merge_expected_head", "revert"})
REQUIRED_ACTIVATION = frozenset({
    "trust_boundary_verified", "api_hostile_simulation_green", "shadow_liveness_validated",
    "platform_enforcement_verified_on_all_repositories", "governance_drift_human_cleared",
})
REQUIRED_MUTATION_RUNTIME_FILES = frozenset({
    ".l5/trust-policy.json", BOOTSTRAP_PATH, "scripts/l5_control_plane.py",
    "scripts/l5_trust_boundary.py", "scripts/l5_activation.py", "scripts/l5_recovery.py",
    "scripts/l5_state_machine.py", "scripts/l5_write_adapter.py",
})


def _manifest_path(path: Path | None = None) -> Path:
    if path is not None: return path
    override = os.environ.get("L5_CONTROL_PLANE_MANIFEST")
    return Path(override) if override else MANIFEST


def load_manifest(path: Path | None = None) -> Mapping[str, Any]:
    try: value = json.loads(_manifest_path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc: raise ValueError("CONTROL_PLANE_UNAVAILABLE") from exc
    if not isinstance(value, Mapping) or value.get("schema_version") != "1.0": raise ValueError("CONTROL_PLANE_INVALID")
    if value.get("control_repository") != "NTinkicht/OneCompany": raise ValueError("CONTROL_PLANE_REPOSITORY_INVALID")
    requirements = value.get("activation_requirements")
    if not isinstance(requirements, list) or not all(isinstance(x, str) for x in requirements) or set(requirements) != REQUIRED_ACTIVATION:
        raise ValueError("CONTROL_PLANE_REQUIREMENTS_INVALID")
    return value


def _git_blob_sha(content: bytes) -> str:
    return hashlib.sha1(f"blob {len(content)}\0".encode("ascii") + content).hexdigest()


def _runtime_roots_safe(root: Path) -> tuple[bool, str]:
    try:
        for path in (root, root / "scripts", root / ".l5"):
            if path.is_symlink() or not path.is_dir(): return False, "CONTROL_PLANE_RUNTIME_PARENT_INVALID"
    except OSError: return False, "CONTROL_PLANE_RUNTIME_PARENT_UNVERIFIABLE"
    return True, "CONTROL_PLANE_RUNTIME_PARENTS_VERIFIED"


def _control_repository_root() -> Path:
    override = os.environ.get("L5_CONTROL_REPOSITORY_ROOT")
    return Path(override).absolute() if override else ROOT


def _git_executable() -> str:
    """Use a deployment-pinned Git executable; never resolve through inherited PATH."""
    override = os.environ.get("L5_GIT_EXECUTABLE")
    if override:
        candidate = Path(override)
        if candidate.is_absolute() and candidate.is_file(): return str(candidate)
        raise OSError("CONTROL_PLANE_GIT_EXECUTABLE_INVALID")
    for candidate in (Path("/usr/bin/git"), Path("/usr/local/bin/git")):
        if candidate.is_file(): return str(candidate)
    raise OSError("CONTROL_PLANE_GIT_EXECUTABLE_UNAVAILABLE")


def _git(control_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    clean_env = {k: v for k in ("SYSTEMROOT", "WINDIR") if (v := os.environ.get(k))}
    clean_env.update({"GIT_NO_REPLACE_OBJECTS": "1", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})
    return subprocess.run([_git_executable(), "--no-replace-objects", "-C", str(control_root), *args], text=True, capture_output=True, check=False, timeout=10, env=clean_env)


def _certified_runtime_blob_map(control_ref: str) -> tuple[dict[str, str] | None, str]:
    if not SHA40.fullmatch(control_ref): return None, "CONTROL_PLANE_REF_NOT_PINNED"
    root = _control_repository_root(); ok, reason = _runtime_roots_safe(root)
    if not ok: return None, reason
    try:
        commit = _git(root, "cat-file", "-e", f"{control_ref}^{{commit}}")
        tree = _git(root, "ls-tree", "-r", control_ref, "--", "scripts", ".l5/trust-policy.json")
    except (OSError, subprocess.SubprocessError): return None, "CONTROL_PLANE_CERTIFIED_REF_UNAVAILABLE"
    if commit.returncode or tree.returncode: return None, "CONTROL_PLANE_CERTIFIED_REF_UNAVAILABLE"
    blobs: dict[str, str] = {}
    try:
        for line in tree.stdout.splitlines():
            metadata, path = line.split("\t", 1); mode, typ, sha = metadata.split(" ", 2)
            if path not in {".l5/trust-policy.json", BOOTSTRAP_PATH} and not L5_SCRIPT.fullmatch(path): continue
            if typ != "blob" or mode not in {"100644", "100755"} or not SHA40.fullmatch(sha) or path in blobs: return None, "CONTROL_PLANE_CERTIFIED_RUNTIME_INVALID"
            blobs[path] = sha
    except ValueError: return None, "CONTROL_PLANE_CERTIFIED_RUNTIME_INVALID"
    if not REQUIRED_MUTATION_RUNTIME_FILES.issubset(blobs): return None, "CONTROL_PLANE_CERTIFIED_RUNTIME_INCOMPLETE"
    return blobs, "CONTROL_PLANE_CERTIFIED_RUNTIME_RESOLVED"


def _is_executable_cache(name: str) -> bool: return bool(L5_PYC.fullmatch(name) or BOOTSTRAP_PYC.fullmatch(name))


def _runtime_import_artifacts_safe() -> tuple[bool, str]:
    if sys.pycache_prefix is not None: return False, "CONTROL_PLANE_RUNTIME_PYCACHE_PREFIX_SET"
    ok, reason = _runtime_roots_safe(ROOT)
    if not ok: return False, reason
    candidates = [ROOT / "scripts"]; cache = ROOT / "scripts" / "__pycache__"
    try:
        if cache.exists():
            if cache.is_symlink() or not cache.is_dir(): return False, "CONTROL_PLANE_RUNTIME_BYTECODE_INVALID"
            candidates.append(cache)
        for directory in candidates:
            for path in directory.iterdir():
                if _is_executable_cache(path.name): return False, "CONTROL_PLANE_RUNTIME_BYTECODE_PRESENT" if path.is_symlink() or path.is_file() else "CONTROL_PLANE_RUNTIME_BYTECODE_INVALID"
    except OSError: return False, "CONTROL_PLANE_RUNTIME_BYTECODE_UNVERIFIABLE"
    return True, "CONTROL_PLANE_RUNTIME_BYTECODE_ABSENT"


def _local_runtime_blob_map() -> tuple[dict[str, str] | None, str]:
    ok, reason = _runtime_roots_safe(ROOT)
    if not ok: return None, reason
    paths = [ROOT / ".l5" / "trust-policy.json", ROOT / BOOTSTRAP_PATH]
    try: paths.extend(sorted((ROOT / "scripts").glob("l5_*.py")))
    except OSError: return None, "CONTROL_PLANE_RUNTIME_SOURCE_UNAVAILABLE"
    blobs = {}
    for path in paths:
        try:
            if path.is_symlink() or not path.is_file(): return None, "CONTROL_PLANE_RUNTIME_SOURCE_INVALID"
            rel = path.relative_to(ROOT).as_posix()
            if rel not in {".l5/trust-policy.json", BOOTSTRAP_PATH} and not L5_SCRIPT.fullmatch(rel): return None, "CONTROL_PLANE_RUNTIME_SOURCE_INVALID"
            blobs[rel] = _git_blob_sha(path.read_bytes())
        except (OSError, ValueError): return None, "CONTROL_PLANE_RUNTIME_SOURCE_UNAVAILABLE"
    if not REQUIRED_MUTATION_RUNTIME_FILES.issubset(blobs): return None, "CONTROL_PLANE_RUNTIME_SOURCE_INCOMPLETE"
    return blobs, "CONTROL_PLANE_RUNTIME_SOURCE_RESOLVED"


def _runtime_source_verified(value: Mapping[str, Any]) -> tuple[bool, str]:
    ref = value.get("control_ref")
    if not isinstance(ref, str) or not SHA40.fullmatch(ref): return False, "CONTROL_PLANE_REF_NOT_PINNED"
    ok, reason = _runtime_import_artifacts_safe()
    if not ok: return False, reason
    certified, reason = _certified_runtime_blob_map(ref)
    if certified is None: return False, reason
    local, reason = _local_runtime_blob_map()
    if local is None: return False, reason
    if set(local) != set(certified): return False, "CONTROL_PLANE_RUNTIME_FILE_SET_MISMATCH"
    if local != certified: return False, "CONTROL_PLANE_RUNTIME_SOURCE_MISMATCH"
    return True, "CONTROL_PLANE_RUNTIME_SOURCE_VERIFIED"


def _source_loaded_bootstrap():
    """Load only the repository bootstrap by absolute path, bypassing sys.path/PYTHONPATH."""
    path = ROOT / BOOTSTRAP_PATH
    spec = importlib.util.spec_from_file_location("_l5_certified_bootstrap", path)
    if spec is None or spec.loader is None: raise ImportError("bootstrap loader unavailable")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    if Path(module.__file__).absolute() != path.absolute(): raise ImportError("bootstrap origin mismatch")
    return module


def _bootstrap_attestation_verified(control_ref: str) -> bool:
    try:
        bootstrap = _source_loaded_bootstrap()
        ok, _reason = bootstrap.bootstrap_runtime()
        return bool(ok and bootstrap.active_attestation_matches(control_ref))
    except (ImportError, OSError, RuntimeError): return False


def mutation_policy(operation: str | None, path: Path | None = None) -> tuple[bool, str]:
    try: value = load_manifest(path)
    except ValueError as exc: return False, str(exc)
    mode = value.get("execution_mode")
    if mode == "LIVE_SAFE":
        if value.get("mutation_allowed") is not True: return False, "CONTROL_PLANE_MUTATIONS_DISABLED"
        if value.get("platform_enforcement") != "DEFERRED_FOR_VALIDATION": return False, "CONTROL_PLANE_LIVE_SAFE_INVALID"
        if operation in LIVE_SAFE_MAIN_CHANGING: return False, "CONTROL_PLANE_LIVE_SAFE_MAIN_CHANGE_BLOCKED"
        return True, "CONTROL_PLANE_LIVE_SAFE"
    if mode != "ACTIVE": return False, "CONTROL_PLANE_SHADOW"
    if value.get("mutation_allowed") is not True: return False, "CONTROL_PLANE_MUTATIONS_DISABLED"
    if value.get("platform_enforcement") != "VERIFIED": return False, "PLATFORM_ENFORCEMENT_NOT_VERIFIED"
    ref = value.get("control_ref")
    if not isinstance(ref, str) or not SHA40.fullmatch(ref): return False, "CONTROL_PLANE_REF_NOT_PINNED"
    evidence = value.get("activation_evidence")
    if not isinstance(evidence, Mapping): return False, "ACTIVATION_EVIDENCE_MISSING"
    if any(evidence.get(name) is not True for name in REQUIRED_ACTIVATION): return False, "ACTIVATION_EVIDENCE_INCOMPLETE"
    if not _bootstrap_attestation_verified(ref): return False, "CONTROL_PLANE_BOOTSTRAP_ATTESTATION_MISSING"
    ok, reason = _runtime_source_verified(value)
    return (True, "CONTROL_PLANE_ACTIVE") if ok else (False, reason)


if __name__ == "__main__":
    allowed, reason = mutation_policy(None); print(json.dumps({"mutation_allowed": allowed, "reason": reason}, sort_keys=True))
