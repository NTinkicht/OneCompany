#!/usr/bin/env python3
"""Install a fresh OneCompany control plane into another repository.

This is an installer, not an upgrade tool. Existing OneCompany deployments should follow docs/UPGRADING.md.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path

from install_identity import resolve_install_principals
from onecompany_lib import ROOT

COPY_PATHS = [
    ".onecompany",
    "agents",
    "company",
    "patterns",
    "overlays",
    "docs",
    "scripts",
    "onecompany.py",
    "AGENTS.md",
    "CLAUDE.md",
    "GEMINI.md",
    ".github/copilot-instructions.md",
    ".github/CODEOWNERS",
    ".github/ISSUE_TEMPLATE",
    ".github/PULL_REQUEST_TEMPLATE.md",
    ".github/workflows/onecompany-validate.yml",
]
# Product installation acceptance tests below rely on worker readiness and
# dispatch evidence verified for the OneCompany SOURCE repository only. They
# run in the source CI, but are not portable into a fresh, unconfigured target.
# All portable policy/security/algorithm tests remain installed and executable.
SOURCE_INSTALLATION_SELFTESTS = frozenset({
    ".onecompany/selftest/test_a3b_activation.py",
    ".onecompany/selftest/test_dispatch_execution.py",
    ".onecompany/selftest/test_integration_promotion_remediation.py",
    ".onecompany/selftest/test_interactive_activation.py",
    ".onecompany/selftest/test_multi_project_isolation.py",
    ".onecompany/selftest/test_qualification_executor.py",
    ".onecompany/selftest/test_zero_spend_router.py",
    ".onecompany/selftest/test_external_capability_register.py",
    ".onecompany/selftest/test_cloud_mistral_wake.py",
    ".onecompany/selftest/test_cloud_grok_scheduled.py",
    ".onecompany/selftest/test_mistral_cloud_review.py",
    ".onecompany/selftest/test_mistral_review_result.py",
    ".onecompany/selftest/test_mistral_review_packet.py",
    ".onecompany/selftest/test_mistral_cloud_work.py",
    ".onecompany/selftest/test_mistral_cloud_start.py",
    ".onecompany/selftest/test_mistral_start_reconcile.py",
    ".onecompany/selftest/test_mistral_pilot_lease.py",
    ".onecompany/selftest/test_grok_cloud_bridge.py",
    ".onecompany/selftest/test_local_quality_evidence.py",
    ".onecompany/selftest/test_phase1_preview_bundle.py",
    ".onecompany/selftest/test_phase1_vertical_smoke.py",
    ".onecompany/selftest/test_phase1_mission_evidence.py",
})

# The source company's strategic plan must never become another company's
# approved installation baseline merely because bootstrap copies whole trees.
SOURCE_ONLY_PLANNING_FILES = frozenset({
    ".onecompany/external-capability-register.json",
    ".onecompany/schemas/external-capability-register.schema.json",
    "docs/MASTER-EVOLUTION-ROADMAP-2026.md",
    "docs/ROADMAP.md",
    "docs/CLOUD-AGENT-QUALIFICATION.md",
    ".github/workflows/onecompany-mistral-vibe-wake.yml",
    ".github/workflows/onecompany-mistral-exact-head-review.yml",
    "scripts/mistral_cloud_review.py",
    "scripts/mistral_review_result.py",
    "scripts/mistral_review_packet.py",
    ".github/workflows/onecompany-mistral-devtest.yml",
    "scripts/mistral_cloud_work.py",
    "scripts/mistral_cloud_start.py",
    ".github/workflows/onecompany-mistral-start.yml",
    ".github/workflows/onecompany-grok-native-evidence.yml",
    "scripts/grok_cloud_bridge.py",
    "scripts/local_quality_evidence.py",
    "scripts/phase1_preview_bundle.py",
    "scripts/phase1_vertical_smoke.py",
    "scripts/phase1_mission_evidence.py",
    "docs/PHASE1-MISSION-EVIDENCE.md",
    "docs/PHASE1-VERTICAL-SMOKE.md",
})
SOURCE_INSTALLATION_EXCLUSIONS = SOURCE_INSTALLATION_SELFTESTS | SOURCE_ONLY_PLANNING_FILES

CONTRACTS = {
    "PRODUCT.md.template": "PRODUCT.md",
    "ARCHITECTURE.md.template": "ARCHITECTURE.md",
    "SECURITY.md.template": "SECURITY.md",
    "QUALITY.md.template": "QUALITY.md",
    "DESIGN.md.template": "DESIGN.md",
    "OPERATIONS.md.template": "OPERATIONS.md",
}
INITIAL_STATE = {
    "$schema": "./schemas/state.schema.json",
    "schema_version": "1.1",
    "generated_or_reconciled_at": None,
    "repository_head": None,
    "company_state": "INITIALIZING",
    "current_work_unit": None,
    "current_pr": None,
    "current_pr_head": None,
    "current_material_authors": [],
    "active_leases": [],
    "active_streams": [],
    "current_gate": None,
    "ready_work_count": 0,
    "safe_start_candidates": [],
    "open_blockers": [],
    "human_decision_required": False,
    "note": (
        "This file is a cache. Reconcile with live GitHub before consequential "
        "autonomous action. Legacy current_* fields are populated only when exactly "
        "one implementation stream is active."
    ),
}


def run_git(target: Path, *args: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(target), *args],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def infer_github_repo(target: Path) -> str | None:
    remote = run_git(target, "remote", "get-url", "origin")
    if not remote:
        return None
    for pattern in (
        r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$",
        r"github\.com/([^/]+)/([^/]+?)(?:\.git)?$",
    ):
        match = re.search(pattern, remote)
        if match:
            return f"{match.group(1)}/{match.group(2)}"
    return None


def infer_default_branch(target: Path) -> str:
    symbolic = run_git(target, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    return symbolic.split("/", 1)[1] if symbolic and "/" in symbolic else "main"


def copy_item(source: Path, target: Path, force: bool, target_root: Path) -> None:
    """Create a bootstrap file through verified directory descriptors.

    Copying through a parent Path can follow a pre-existing or swapped
    symlink. Exclusive descriptor-relative creation avoids following target
    parents or an attacker-supplied destination leaf.
    """
    if source.relative_to(ROOT).as_posix() in SOURCE_INSTALLATION_EXCLUSIONS:
        return
    if source.is_dir():
        for child in source.rglob("*"):
            if not child.is_dir():
                copy_item(child, target / child.relative_to(source), force, target_root)
        return
    if force:
        raise ValueError("bootstrap is install-only and cannot overwrite existing files")
    relative = target.relative_to(target_root)
    if not relative.parts or any(part in ("", ".", "..") for part in relative.parts):
        raise ValueError("unsafe bootstrap destination")
    descriptors = [_open_root_directory(target_root)]
    try:
        for component in relative.parts[:-1]:
            descriptors.append(_open_directory_at(descriptors[-1], component, create=True))
        mode = stat.S_IMODE(source.stat().st_mode)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        try:
            file_fd = os.open(relative.name, flags, mode=mode, dir_fd=descriptors[-1])
        except FileExistsError as exc:
            raise FileExistsError(f"bootstrap refuses existing project file {target}") from exc
        try:
            with os.fdopen(file_fd, "wb") as destination, source.open("rb") as original:
                shutil.copyfileobj(original, destination)
                destination.flush()
                os.fchmod(destination.fileno(), mode)
                os.fsync(destination.fileno())
        except Exception:
            os.unlink(relative.name, dir_fd=descriptors[-1])
            raise
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def preflight_copy_paths(target: Path) -> None:
    """Reject target collisions before writing even one installer file.

    Existing product files must never be overwritten or leave an
    unrepairable half-install when a later COPY_PATHS entry collides.
    """
    collisions: set[str] = set()
    for item in COPY_PATHS:
        source = ROOT / item
        if not source.exists():
            continue
        leaves = (
            (child for child in source.rglob("*") if not child.is_dir())
            if source.is_dir()
            else (source,)
        )
        for leaf in leaves:
            relative = leaf.relative_to(ROOT).as_posix()
            if relative in SOURCE_INSTALLATION_EXCLUSIONS:
                continue
            destination = target / relative
            if destination.exists() or destination.is_symlink():
                collisions.add(relative)
                continue
            for parent in destination.parents:
                if parent == target:
                    break
                if parent.is_symlink():
                    collisions.add(parent.relative_to(target).as_posix())
                    break
                if parent.exists() and not parent.is_dir():
                    collisions.add(parent.relative_to(target).as_posix())
                    break
    if collisions:
        raise FileExistsError(
            "bootstrap refuses existing project files before installation: "
            + ", ".join(sorted(collisions))
            + "; resolve naming collisions without overwriting the product"
        )


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _generic_evidence_ref(ref: object) -> bool:
    """Return true only for repo-relative or generic fixture evidence."""
    return isinstance(ref, str) and ref.startswith(("repo:", "fixture:"))


def _validate_bootstrap_knowledge_provenance(entry: dict, path: Path) -> None:
    """Reject project identities, commits, URLs, or validation refs from reusable lessons."""
    source_evidence = entry.get("source_evidence")
    if not isinstance(source_evidence, list) or not source_evidence:
        raise ValueError(f"bootstrap-safe knowledge requires generic provenance: {path.name}")
    for evidence in source_evidence:
        if not isinstance(evidence, dict):
            raise ValueError(f"bootstrap-safe knowledge provenance is malformed: {path.name}")
        if evidence.get("actor") != "onecompany":
            raise ValueError(
                f"bootstrap-safe knowledge cannot inherit project reviewer identity: {path.name}"
            )
        if evidence.get("commit") is not None:
            raise ValueError(
                f"bootstrap-safe knowledge cannot inherit project commit identity: {path.name}"
            )
        if not _generic_evidence_ref(evidence.get("ref")):
            raise ValueError(
                f"bootstrap-safe knowledge cannot inherit project-specific evidence: {path.name}"
            )

    validation = entry.get("validation")
    if not isinstance(validation, dict):
        raise ValueError(f"bootstrap-safe knowledge validation is malformed: {path.name}")
    refs = validation.get("evidence_refs")
    if not isinstance(refs, list) or not refs or not all(_generic_evidence_ref(ref) for ref in refs):
        raise ValueError(
            f"bootstrap-safe knowledge cannot inherit project validation evidence: {path.name}"
        )


def _secure_directory_flags() -> int:
    """Return fail-closed flags for descriptor-bound bootstrap cleanup."""
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    if nofollow == 0 or directory == 0:
        raise ValueError("secure descriptor-bound knowledge cleanup is unsupported")
    return os.O_RDONLY | nofollow | directory


def _open_root_directory(path: Path) -> int:
    """Open a knowledge root without following or racing a replacement symlink."""
    flags = _secure_directory_flags()
    try:
        before = os.lstat(path)
        fd = os.open(str(path), flags)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise ValueError(f"knowledge root is unsafe during bootstrap: {exc}") from exc
    try:
        opened = os.fstat(fd)
        if not stat.S_ISDIR(before.st_mode) or not stat.S_ISDIR(opened.st_mode):
            raise ValueError("knowledge root must be a directory during bootstrap")
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError("knowledge root changed during bootstrap cleanup")
        return fd
    except Exception:
        os.close(fd)
        raise


def _open_directory_at(parent_fd: int, name: str, *, create: bool) -> int:
    """Open one child directory relative to a trusted parent and verify its identity."""
    flags = _secure_directory_flags()
    try:
        fd = os.open(name, flags, dir_fd=parent_fd)
    except FileNotFoundError:
        if not create:
            raise
        try:
            os.mkdir(name, mode=0o755, dir_fd=parent_fd)
        except FileExistsError:
            pass
        try:
            fd = os.open(name, flags, dir_fd=parent_fd)
        except OSError as exc:
            raise ValueError(f"knowledge directory {name} is unsafe during bootstrap: {exc}") from exc
    except OSError as exc:
        raise ValueError(f"knowledge directory {name} is unsafe during bootstrap: {exc}") from exc
    try:
        linked = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        opened = os.fstat(fd)
        if not stat.S_ISDIR(linked.st_mode) or not stat.S_ISDIR(opened.st_mode):
            raise ValueError(f"knowledge directory {name} must remain a directory")
        if (linked.st_dev, linked.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError(f"knowledge directory {name} changed during bootstrap cleanup")
        return fd
    except Exception:
        os.close(fd)
        raise


def _read_json_at(directory_fd: int, name: str) -> dict:
    """Read one regular JSON entry relative to an already verified directory."""
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(name, os.O_RDONLY | nofollow, dir_fd=directory_fd)
    except OSError as exc:
        raise ValueError(f"knowledge entry {name} is unsafe during bootstrap: {exc}") from exc
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"knowledge entry {name} must be a regular file")
        with os.fdopen(fd, "r", encoding="utf-8") as handle:
            fd = -1
            value = json.load(handle)
        if not isinstance(value, dict):
            raise ValueError(f"knowledge entry {name} must be a JSON object")
        return value
    except json.JSONDecodeError:
        raise
    except OSError as exc:
        raise ValueError(f"cannot read knowledge entry {name}: {exc}") from exc
    finally:
        if fd >= 0:
            os.close(fd)


def _unlink_json_entries(directory_fd: int) -> None:
    """Delete JSON directory entries without ever following their targets."""
    try:
        names = os.listdir(directory_fd)
    except OSError as exc:
        raise ValueError(f"cannot enumerate knowledge directory: {exc}") from exc
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                raise ValueError(f"knowledge JSON entry cannot be a directory: {name}")
            os.unlink(name, dir_fd=directory_fd)
        except OSError as exc:
            raise ValueError(f"cannot safely remove knowledge entry {name}: {exc}") from exc


def _remove_tree_at(parent_fd: int, name: str) -> None:
    """Recursively remove one directory tree through no-follow relative descriptors."""
    directory_fd = _open_directory_at(parent_fd, name, create=False)
    try:
        for child in os.listdir(directory_fd):
            metadata = os.stat(child, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                _remove_tree_at(directory_fd, child)
            else:
                os.unlink(child, dir_fd=directory_fd)
    except OSError as exc:
        raise ValueError(f"cannot safely clear knowledge transaction state: {exc}") from exc
    finally:
        os.close(directory_fd)
    try:
        os.rmdir(name, dir_fd=parent_fd)
    except OSError as exc:
        raise ValueError(f"cannot safely remove knowledge transaction directory: {exc}") from exc


def initialize_knowledge(target: Path) -> None:
    """Keep only generic advisory lessons in a fresh installation."""
    root = target / ".onecompany" / "knowledge"
    try:
        root_fd = _open_root_directory(root)
    except FileNotFoundError:
        return
    try:
        for state_name in ("candidate", "archived"):
            directory_fd = _open_directory_at(root_fd, state_name, create=True)
            try:
                _unlink_json_entries(directory_fd)
            finally:
                os.close(directory_fd)

        try:
            transaction_metadata = os.stat(
                ".transactions", dir_fd=root_fd, follow_symlinks=False
            )
        except FileNotFoundError:
            transaction_metadata = None
        if transaction_metadata is not None:
            if not stat.S_ISDIR(transaction_metadata.st_mode):
                raise ValueError("knowledge transaction state is unsafe during bootstrap")
            _remove_tree_at(root_fd, ".transactions")

        current_fd = _open_directory_at(root_fd, "current", create=True)
        try:
            for name in os.listdir(current_fd):
                if not name.endswith(".json"):
                    continue
                entry = _read_json_at(current_fd, name)
                if entry.get("bootstrap_safe") is not True:
                    try:
                        os.unlink(name, dir_fd=current_fd)
                    except OSError as exc:
                        raise ValueError(
                            f"cannot safely remove project-specific knowledge {name}: {exc}"
                        ) from exc
                    continue
                if entry.get("authority") != "advisory_only" or entry.get("authority_effects") != []:
                    raise ValueError(
                        f"bootstrap-safe knowledge must remain advisory-only: {name}"
                    )
                _validate_bootstrap_knowledge_provenance(entry, Path(name))
        finally:
            os.close(current_fd)
    finally:
        os.close(root_fd)


def initialize_contracts(target: Path) -> None:
    source_dir = ROOT / ".onecompany" / "templates" / "contracts"
    for source_name, target_name in CONTRACTS.items():
        destination = target / target_name
        if destination.exists():
            print(f"KEEP existing project contract {target_name}")
            continue
        shutil.copy2(source_dir / source_name, destination)
        print(f"INIT project contract {target_name}")


def configure_codeowners(target: Path, owner: str) -> None:
    path = target / ".github" / "CODEOWNERS"
    if not path.exists():
        raise FileNotFoundError("bootstrap copy did not contain .github/CODEOWNERS")
    lines = []
    protected_paths = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            lines.append(line)
            continue
        parts = stripped.split()
        if not parts[0].startswith("/") or len(parts) < 2:
            raise ValueError("unexpected source CODEOWNERS format during bootstrap")
        lines.append(f"{parts[0]} {owner}")
        protected_paths += 1
    if protected_paths == 0:
        raise ValueError("bootstrap requires protected CODEOWNERS paths")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def configure_root_identity(target: Path, login: str) -> None:
    path = target / ".onecompany" / "identity.json"
    if not path.exists():
        raise FileNotFoundError("bootstrap copy did not contain .onecompany/identity.json")
    identity = json.loads(path.read_text(encoding="utf-8"))
    principals = identity.get("principals", [])
    roots = [
        item
        for item in principals
        if isinstance(item, dict) and "root" in item.get("authorities", [])
    ]
    if len(roots) != 1:
        raise ValueError(
            "template identity policy must contain exactly one root principal before bootstrap"
        )
    root = roots[0]
    if root.get("actor_id") != "human-owner":
        raise ValueError("template root principal must map to actor_id human-owner")
    root["login"] = login
    identity["principals"] = [root]
    write_json(path, identity)


def initialize_control_plane(
    target: Path,
    project_name: str,
    repository: str,
    default_branch: str,
) -> None:
    config_path = target / ".onecompany" / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config.setdefault("project", {})["name"] = project_name
    config["project"]["repository"] = repository
    config["project"]["default_branch"] = default_branch
    write_json(config_path, config)

    readiness_path = target / ".onecompany" / "readiness.json"
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    for actor in readiness.get("actors", []):
        is_root = actor.get("actor_id") == "human-owner"
        actor["setup_state"] = "ready" if is_root else "not_started"
        actor["verified_surfaces"] = ["bootstrap-explicit-root-principal"] if is_root else []
        actor["verified_capabilities"] = ["repository_intelligence"] if is_root else []
        actor["temporarily_unavailable_capabilities"] = []
        actor["repository_access"] = {
            "read": is_root,
            "write": False,
            "review": False,
            "merge": False,
        }
        actor["unattended"] = {"configured": False, "verified": False}
        actor["capacity"] = {
            "implementation_streams": 0,
            "measured": False,
            "observed_at": None,
            "evidence": [],
        }
        actor["last_verified_at"] = None
        actor["evidence"] = (
            ["Explicit root principal selected during bootstrap; write/review/merge remain unverified"]
            if is_root
            else []
        )
    write_json(readiness_path, readiness)

    actors_path = target / ".onecompany" / "actors.json"
    actors = json.loads(actors_path.read_text(encoding="utf-8"))
    for actor in actors.get("actors", []):
        is_root = actor.get("id") == "human-owner"
        actor["enabled"] = is_root
        actor["configured"] = is_root
    write_json(actors_path, actors)

    dispatch_path = target / ".onecompany" / "dispatch.json"
    dispatch = json.loads(dispatch_path.read_text(encoding="utf-8"))
    for actor in dispatch.get("actors", []):
        for mechanism in actor.get("mechanisms", []):
            mechanism["configured"] = (
                actor.get("actor_id") == "human-owner"
                and mechanism.get("kind") == "manual"
            )
            mechanism["evidence"] = []
            if actor.get("actor_id") == "human-owner" and mechanism.get("kind") == "manual":
                # Only the bootstrap-selected human may perform this minimal
                # read-only capability. No inherited write/review/merge proof.
                mechanism["capabilities"] = ["repository_intelligence"]
    write_json(dispatch_path, dispatch)

    ledger_path = target / ".onecompany" / "ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["enabled"] = False
    ledger["issue_number"] = None
    ledger["trusted_publisher_logins"] = []
    write_json(ledger_path, ledger)

    supervision_path = target / ".onecompany" / "supervision.json"
    supervision = json.loads(supervision_path.read_text(encoding="utf-8"))
    supervision["enabled"] = False
    supervision["mode"] = "observe_only"
    supervision.setdefault("coordination", {})["team_room_issue_number"] = None
    github_actions = supervision.setdefault("github_actions", {})
    github_actions["enabled"] = False
    github_actions["may_post_team_room"] = False
    github_actions["may_failover"] = False
    github_actions["may_merge"] = False
    chatgpt_tasks = supervision.setdefault("chatgpt_tasks", {})
    chatgpt_tasks["enabled"] = False
    chatgpt_tasks["may_mutate"] = False
    write_json(supervision_path, supervision)

    write_json(target / ".onecompany" / "queue.json", {"$schema": "./schemas/queue.schema.json", "schema_version": "1.1", "work_units": []})
    write_json(target / ".onecompany" / "portfolio.json", {"$schema": "./schemas/portfolio.schema.json", "schema_version": "1.0", "entities": [], "links": []})
    write_json(target / ".onecompany" / "requirements-catalog.json", {"$schema": "./schemas/requirements-catalog.schema.json", "schema_version": "1.0", "requirements": [], "acceptance_criteria": []})
    write_json(target / ".onecompany" / "risk-register.json", {"$schema": "./schemas/risk-register.schema.json", "schema_version": "1.0", "risks": []})
    write_json(target / ".onecompany" / "state.json", INITIAL_STATE)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--repository")
    parser.add_argument("--project-name")
    parser.add_argument("--default-branch")
    parser.add_argument("--code-owner")
    parser.add_argument("--root-principal")
    parser.add_argument("--initialize-contracts", action="store_true")
    args = parser.parse_args()

    target = Path(args.target).resolve()
    if (target / ".onecompany").exists():
        raise FileExistsError("target already contains .onecompany; bootstrap is install-only")
    repository = args.repository or infer_github_repo(target)
    if not repository:
        raise ValueError("--repository is required when GitHub origin cannot be inferred")
    project_name = args.project_name or repository.split("/", 1)[-1]
    default_branch = args.default_branch or infer_default_branch(target)
    code_owner, root_principal = resolve_install_principals(
        repository=repository,
        code_owner=args.code_owner,
        root_principal=args.root_principal,
    )

    preflight_copy_paths(target)
    for item in COPY_PATHS:
        source = ROOT / item
        if source.exists():
            copy_item(source, target / item, False, target)
    configure_codeowners(target, code_owner)
    configure_root_identity(target, root_principal)
    initialize_control_plane(target, project_name, repository, default_branch)
    initialize_knowledge(target)
    if args.initialize_contracts:
        initialize_contracts(target)
    print(f"OneCompany bootstrapped into {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
