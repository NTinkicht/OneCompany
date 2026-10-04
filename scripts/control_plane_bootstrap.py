#!/usr/bin/env python3
"""Dependency-free pre-import trust boundary for future ACTIVE L5 execution.

This module is intentionally outside the ``l5_*.py`` runtime namespace and is
protected as an always-human governance path. It performs the checks that must
happen before candidate L5 modules are imported. The current control plane
remains LIVE_SAFE; future ACTIVE activation requires a separately governed
update that admits the protected-main control commit here.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Mapping

SOURCE_FILE = Path(__file__).absolute()
ROOT = SOURCE_FILE.parent.parent
MANIFEST = ROOT / ".l5" / "control-plane.json"
SHA40 = re.compile(r"^[0-9a-f]{40}$")
L5_SCRIPT = re.compile(r"^scripts/l5_[^/]+\.py$")
L5_PYC = re.compile(r"^l5_[^/]+(?:\.[^/]+)*\.pyc$")
BOOTSTRAP_PYC = re.compile(r"^control_plane_bootstrap(?:\.[^/]+)*\.pyc$")
BOOTSTRAP_PATH = "scripts/control_plane_bootstrap.py"

TRUSTED_CONTROL_REFS = frozenset({
    "88d2c6632543d937add00e1e9da493a260638057",
})

_ATTESTATION: tuple[str, str] | None = None


def _manifest_path(path: Path | None = None) -> Path:
    """Resolve an explicit manifest or the operator-provided manifest path."""
    if path is not None:
        return path
    override = os.environ.get("L5_CONTROL_PLANE_MANIFEST")
    return Path(override) if override else MANIFEST


def _assert_regular_runtime_roots(root: Path) -> None:
    """Reject symlinked repository/runtime roots before any L5 import."""
    for path in (root, root / "scripts", root / ".l5"):
        try:
            if path.is_symlink() or not path.is_dir():
                raise RuntimeError("L5_BOOTSTRAP_RUNTIME_ROOT_INVALID")
        except OSError as exc:
            raise RuntimeError("L5_BOOTSTRAP_RUNTIME_ROOT_UNVERIFIABLE") from exc


def _is_executable_cache(name: str) -> bool:
    """Return whether a cache artifact could supply L5/bootstrap bytecode."""
    return bool(L5_PYC.fullmatch(name) or BOOTSTRAP_PYC.fullmatch(name))


def prepare_source_only_l5_imports(root: Path | None = None) -> None:
    """Remove executable L5/bootstrap bytecode and disable bytecode generation."""
    runtime_root = root or ROOT
    _assert_regular_runtime_roots(runtime_root)
    scripts = runtime_root / "scripts"
    cache = scripts / "__pycache__"
    try:
        if cache.exists():
            if cache.is_symlink() or not cache.is_dir():
                raise RuntimeError("L5_BOOTSTRAP_BYTECODE_CACHE_INVALID")
            for path in cache.iterdir():
                if not _is_executable_cache(path.name):
                    continue
                if path.is_symlink() or not path.is_file():
                    raise RuntimeError("L5_BOOTSTRAP_BYTECODE_ARTIFACT_INVALID")
                path.unlink()
        for path in scripts.iterdir():
            if not _is_executable_cache(path.name):
                continue
            if path.is_symlink() or not path.is_file():
                raise RuntimeError("L5_BOOTSTRAP_BYTECODE_ARTIFACT_INVALID")
            path.unlink()
    except OSError as exc:
        raise RuntimeError("L5_BOOTSTRAP_BYTECODE_CLEAN_FAILED") from exc
    sys.dont_write_bytecode = True


def _git_env() -> dict[str, str]:
    """Return a minimal Git environment without repository redirection state."""
    clean: dict[str, str] = {}
    for name in ("PATH", "SYSTEMROOT", "WINDIR", "PATHEXT"):
        value = os.environ.get(name)
        if value:
            clean[name] = value
    clean["GIT_NO_REPLACE_OBJECTS"] = "1"
    clean["GIT_CONFIG_NOSYSTEM"] = "1"
    clean["GIT_CONFIG_GLOBAL"] = os.devnull
    return clean


def _git(control_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run one bounded read-only Git object query with replacement refs off."""
    return subprocess.run(
        ["git", "--no-replace-objects", "-C", str(control_root), *args],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
        env=_git_env(),
    )


def _git_blob_sha(content: bytes) -> str:
    """Return the SHA-1 object identity Git assigns to exact file bytes."""
    header = f"blob {len(content)}\0".encode("ascii")
    return hashlib.sha1(header + content).hexdigest()


def _control_repository_root() -> Path:
    """Return the credential-free object store used for control certification."""
    override = os.environ.get("L5_CONTROL_REPOSITORY_ROOT")
    return Path(override).absolute() if override else ROOT


def _certified_runtime(control_ref: str) -> dict[str, str]:
    """Resolve the complete certified L5 namespace from one admitted commit."""
    if control_ref not in TRUSTED_CONTROL_REFS:
        raise RuntimeError("L5_BOOTSTRAP_CONTROL_REF_NOT_TRUSTED")
    control_root = _control_repository_root()
    _assert_regular_runtime_roots(control_root)
    try:
        commit = _git(control_root, "cat-file", "-e", f"{control_ref}^{{commit}}")
        tree = _git(
            control_root,
            "ls-tree",
            "-r",
            control_ref,
            "--",
            "scripts",
            ".l5/trust-policy.json",
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("L5_BOOTSTRAP_CERTIFIED_REF_UNAVAILABLE") from exc
    if commit.returncode != 0 or tree.returncode != 0:
        raise RuntimeError("L5_BOOTSTRAP_CERTIFIED_REF_UNAVAILABLE")

    blobs: dict[str, str] = {}
    try:
        for line in tree.stdout.splitlines():
            metadata, path = line.split("\t", 1)
            mode, object_type, blob_sha = metadata.split(" ", 2)
            if path not in {".l5/trust-policy.json", BOOTSTRAP_PATH} and not L5_SCRIPT.fullmatch(path):
                continue
            if object_type != "blob" or mode not in {"100644", "100755"} or not SHA40.fullmatch(blob_sha):
                raise RuntimeError("L5_BOOTSTRAP_CERTIFIED_RUNTIME_INVALID")
            if path in blobs:
                raise RuntimeError("L5_BOOTSTRAP_CERTIFIED_RUNTIME_INVALID")
            blobs[path] = blob_sha
    except ValueError as exc:
        raise RuntimeError("L5_BOOTSTRAP_CERTIFIED_RUNTIME_INVALID") from exc
    if BOOTSTRAP_PATH not in blobs or ".l5/trust-policy.json" not in blobs:
        raise RuntimeError("L5_BOOTSTRAP_CERTIFIED_RUNTIME_INCOMPLETE")
    return blobs


def _local_runtime(root: Path) -> dict[str, str]:
    """Hash the executing bootstrap, trust policy, and complete L5 namespace."""
    _assert_regular_runtime_roots(root)
    scripts = root / "scripts"
    paths = [root / ".l5" / "trust-policy.json", root / BOOTSTRAP_PATH]
    try:
        paths.extend(sorted(scripts.glob("l5_*.py")))
    except OSError as exc:
        raise RuntimeError("L5_BOOTSTRAP_RUNTIME_SOURCE_UNAVAILABLE") from exc

    blobs: dict[str, str] = {}
    for path in paths:
        try:
            if path.is_symlink() or not path.is_file():
                raise RuntimeError("L5_BOOTSTRAP_RUNTIME_SOURCE_INVALID")
            relative = path.relative_to(root).as_posix()
            if relative not in {".l5/trust-policy.json", BOOTSTRAP_PATH} and not L5_SCRIPT.fullmatch(relative):
                raise RuntimeError("L5_BOOTSTRAP_RUNTIME_SOURCE_INVALID")
            blobs[relative] = _git_blob_sha(path.read_bytes())
        except OSError as exc:
            raise RuntimeError("L5_BOOTSTRAP_RUNTIME_SOURCE_UNAVAILABLE") from exc
    return blobs


def bootstrap_runtime(manifest_path: Path | None = None) -> tuple[bool, str]:
    """Prepare imports and attest an admitted ACTIVE runtime before L5 imports."""
    global _ATTESTATION
    _ATTESTATION = None
    prepare_source_only_l5_imports()
    try:
        value = json.loads(_manifest_path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, "L5_BOOTSTRAP_MANIFEST_UNAVAILABLE"
    if not isinstance(value, Mapping):
        return False, "L5_BOOTSTRAP_MANIFEST_INVALID"
    if value.get("execution_mode") != "ACTIVE":
        return True, "L5_BOOTSTRAP_NON_ACTIVE"
    control_ref = value.get("control_ref")
    if not isinstance(control_ref, str) or not SHA40.fullmatch(control_ref):
        return False, "L5_BOOTSTRAP_CONTROL_REF_NOT_PINNED"
    try:
        certified = _certified_runtime(control_ref)
        local = _local_runtime(ROOT)
    except RuntimeError as exc:
        return False, str(exc)
    if set(certified) != set(local):
        return False, "L5_BOOTSTRAP_RUNTIME_FILE_SET_MISMATCH"
    if certified != local:
        return False, "L5_BOOTSTRAP_RUNTIME_SOURCE_MISMATCH"
    digest = hashlib.sha256(
        json.dumps(certified, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    _ATTESTATION = (control_ref, digest)
    return True, "L5_BOOTSTRAP_ACTIVE_ATTESTED"


def active_attestation_matches(control_ref: str) -> bool:
    """Return whether the pre-import bootstrap attested this exact control ref."""
    return _ATTESTATION is not None and _ATTESTATION[0] == control_ref
