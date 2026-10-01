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
    ".onecompany/selftest/test_mistral_external_review.py",
    ".onecompany/selftest/test_mistral_external_dispatch.py",
    ".onecompany/selftest/test_mistral_review_result.py",
    ".onecompany/selftest/test_mistral_review_packet.py",
    ".onecompany/selftest/test_mistral_cloud_work.py",
    ".onecompany/selftest/test_mistral_cloud_start.py",
    ".onecompany/selftest/test_mistral_start_reconcile.py",
    ".onecompany/selftest/test_mistral_pilot_lease.py",
    ".onecompany/selftest/test_grok_cloud_bridge.py",
    ".onecompany/selftest/test_local_quality_evidence.py",
    ".onecompany/selftest/test_gemma_l4_worker.py",
    ".onecompany/selftest/test_phase1_preview_bundle.py",
    ".onecompany/selftest/test_phase1_vertical_smoke.py",
    ".onecompany/selftest/test_phase1_mission_evidence.py",
    # L5 activation is source-installation governance: its pinned reviewer
    # registry lives in the source repo's human-governed .l5 policy. A fresh
    # bootstrap intentionally receives neither that authority nor those source
    # identities. The L5 scripts therefore remain fail-closed until the target
    # establishes its own reviewed trust policy, while this source-specific
    # activation acceptance test continues to run in OneCompany CI.
    ".onecompany/selftest/test_l5_activation.py",
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
    "scripts/mistral_external_review.py",
    "scripts/mistral_external_dispatch.py",
    ".github/workflows/onecompany-mistral-external-dispatch.yml",
    ".github/workflows/onecompany-mistral-external-review.yml",
    "docs/MISTRAL-EXTERNAL-REVIEW.md",
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
    "scripts/gemma_l4_worker.py",
    ".github/prompts/gemma-l4-worker.md",
    ".github/workflows/gemma-l4-worker.yml",
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
        candidates = [source]
        if source.is_dir():
            candidates.extend(child for child in source.rglob("*") if not child.is_dir())
        for child in candidates:
            if child.is_dir():
                continue
            relative = child.relative_to(ROOT)
            if relative.as_posix() in SOURCE_INSTALLATION_EXCLUSIONS:
                continue
            destination = target / relative
            if destination.exists() or destination.is_symlink():
                collisions.add(relative.as_posix())
    if collisions:
        raise FileExistsError(
            "bootstrap refuses existing project files: " + ", ".join(sorted(collisions))
        )


def _open_root_directory(target: Path) -> int:
    """Open target root without following a symlink."""
    return os.open(target, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)


def _open_directory_at(parent_fd: int, name: str, *, create: bool) -> int:
    """Open a child directory without following symbolic links."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        return os.open(name, flags, dir_fd=parent_fd)
    except FileNotFoundError:
        if not create:
            raise
        try:
            os.mkdir(name, mode=0o755, dir_fd=parent_fd)
        except FileExistsError:
            pass
        return os.open(name, flags, dir_fd=parent_fd)


def write_json(path: Path, data: dict, *, target_root: Path) -> None:
    """Create a JSON bootstrap file without following target symlinks."""
    relative = path.relative_to(target_root)
    descriptors = [_open_root_directory(target_root)]
    try:
        for component in relative.parts[:-1]:
            descriptors.append(_open_directory_at(descriptors[-1], component, create=True))
        try:
            file_fd = os.open(
                relative.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                mode=0o644,
                dir_fd=descriptors[-1],
            )
        except FileExistsError as exc:
            raise FileExistsError(f"bootstrap refuses existing project file {path}") from exc
        try:
            with os.fdopen(file_fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            os.unlink(relative.name, dir_fd=descriptors[-1])
            raise
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def scrub_runtime(target: Path, *, root_principal: str, root_actor: str = "human-owner") -> None:
    """Reset project-specific runtime state in a fresh target."""
    onecompany = target / ".onecompany"
    write_json(onecompany / "state.json", INITIAL_STATE, target_root=target)

    queue_path = onecompany / "queue.json"
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    queue["work_units"] = []
    queue_path.unlink()
    write_json(queue_path, queue, target_root=target)

    portfolio_path = onecompany / "portfolio.json"
    portfolio = json.loads(portfolio_path.read_text(encoding="utf-8"))
    portfolio["entities"] = []
    portfolio["links"] = []
    portfolio_path.unlink()
    write_json(portfolio_path, portfolio, target_root=target)

    catalog_path = onecompany / "requirements-catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["requirements"] = []
    catalog_path.unlink()
    write_json(catalog_path, catalog, target_root=target)

    ledger_path = onecompany / "ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger.update({
        "enabled": False,
        "repository": None,
        "branch": "l5/controller-ledger",
        "path": ".l5/controller-ledger.json",
        "issue_number": None,
        "trusted_publisher_logins": [],
    })
    ledger_path.unlink()
    write_json(ledger_path, ledger, target_root=target)

    supervision_path = onecompany / "supervision.json"
    supervision = json.loads(supervision_path.read_text(encoding="utf-8"))
    supervision.update({"enabled": False, "mode": "observe_only"})
    supervision["coordination"] = {
        "team_room_issue_number": None,
        "work_queue_path": ".onecompany/queue.json",
        "state_path": ".onecompany/state.json",
        "ledger_config_path": ".onecompany/ledger.json",
    }
    supervision["github_actions"] = {
        "enabled": False,
        "may_post_team_room": False,
        "may_failover": False,
        "may_merge": False,
    }
    supervision["chatgpt_tasks"] = {
        "enabled": False,
        "may_mutate": False,
    }
    supervision_path.unlink()
    write_json(supervision_path, supervision, target_root=target)

    handoffs_path = onecompany / "handoffs.json"
    handoffs = json.loads(handoffs_path.read_text(encoding="utf-8"))
    runtime = handoffs.setdefault("runtime", {})
    runtime.update({
        "current_autonomy_level": "L1",
        "scheduled_chatgpt_mutation_allowed": False,
        "automatic_failover_allowed": False,
        "automatic_merge_allowed": False,
        "continuous_next_work_allowed": False,
    })
    handoffs_path.unlink()
    write_json(handoffs_path, handoffs, target_root=target)

    actors_path = onecompany / "actors.json"
    actors_doc = json.loads(actors_path.read_text(encoding="utf-8"))
    for actor in actors_doc.get("actors", []):
        is_root = actor.get("id") == root_actor
        actor["configured"] = is_root
        actor["enabled"] = is_root
    actors_path.unlink()
    write_json(actors_path, actors_doc, target_root=target)

    readiness_path = onecompany / "readiness.json"
    readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    for actor in readiness.get("actors", []):
        is_root = actor.get("actor_id") == root_actor
        actor["setup_state"] = "ready" if is_root else "not_started"
        actor["verified_surfaces"] = ["bootstrap-explicit-root-principal"] if is_root else []
        actor["verified_capabilities"] = ["repository_intelligence"] if is_root else []
        actor["repository_access"] = {
            "read": is_root,
            "write": False,
            "review": False,
            "merge": False,
        }
        actor["unattended"] = {
            "configured": False,
            "verified": False,
            "mechanism": None,
        }
        actor["capacity"] = {"measured": False}
    readiness_path.unlink()
    write_json(readiness_path, readiness, target_root=target)

    dispatch_path = onecompany / "dispatch.json"
    dispatch = json.loads(dispatch_path.read_text(encoding="utf-8"))
    for actor in dispatch.get("actors", []):
        for mechanism in actor.get("mechanisms", []):
            mechanism["evidence"] = []
            mechanism["configured"] = actor.get("actor_id") == root_actor and mechanism.get("kind") == "manual"
    dispatch_path.unlink()
    write_json(dispatch_path, dispatch, target_root=target)

    identity_path = onecompany / "identity.json"
    identity = json.loads(identity_path.read_text(encoding="utf-8"))
    identity["principals"] = [{"login": root_principal, "authorities": ["root"]}]
    identity_path.unlink()
    write_json(identity_path, identity, target_root=target)


def initialize_knowledge(target: Path) -> None:
    """Retain only safe generic lessons when bootstrapping a new company."""
    knowledge_dir = target / ".onecompany" / "knowledge"
    if not knowledge_dir.exists():
        return
    for path in sorted(knowledge_dir.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        entries = doc.get("entries") if isinstance(doc, dict) else None
        if not isinstance(entries, list):
            path.unlink()
            continue
        safe_entries = []
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("bootstrap_safe") is not True:
                continue
            _validate_bootstrap_knowledge_provenance(entry, path)
            sanitized = dict(entry)
            sanitized["status"] = "candidate"
            sanitized["source"] = "bootstrap_safe_generic_lesson"
            sanitized["reviewed_by"] = None
            sanitized["validated_at"] = None
            safe_entries.append(sanitized)
        doc["entries"] = safe_entries
        path.unlink()
        write_json(path, doc, target_root=target)


def _contains_disallowed_provenance_value(value: object, *, field: str) -> bool:
    if not isinstance(value, str):
        return True
    lower = value.lower()
    if "github.com/" in lower or re.search(r"\b[0-9a-f]{40}\b", lower):
        return True
    if field in {"source_issue", "source_pr"} and value not in {"", "none", "n/a"}:
        return True
    return False


def _allowed_bootstrap_evidence_ref(ref: object) -> bool:
    return isinstance(ref, str) and ref.startswith(("repo:", "fixture:"))


def _validate_bootstrap_knowledge_provenance(entry: dict, path: Path) -> None:
    """Reject project identities, commits, URLs, or validation refs from reusable lessons."""
    source_evidence = entry.get("source_evidence", {})
    validation = entry.get("validation", {})
    if not isinstance(source_evidence, dict) or not isinstance(validation, dict):
        raise ValueError(f"unsafe bootstrap-safe knowledge provenance in {path.name}")
    for field in ("source_issue", "source_pr", "source_commit", "source_url"):
        value = source_evidence.get(field, "")
        if _contains_disallowed_provenance_value(value, field=field):
            raise ValueError(f"unsafe bootstrap-safe knowledge field {field} in {path.name}")
    refs = validation.get("evidence_refs", [])
    if not isinstance(refs, list) or any(not _allowed_bootstrap_evidence_ref(ref) for ref in refs):
        raise ValueError(f"unsafe bootstrap-safe knowledge evidence refs in {path.name}")


def bootstrap(
    target: Path,
    *,
    repository: str | None = None,
    project_name: str | None = None,
    default_branch: str | None = None,
    code_owner: str | None = None,
    root_principal: str | None = None,
    initialize_contracts: bool = False,
    force: bool = False,
) -> None:
    """Install a fresh, source-neutral OneCompany control plane."""
    if force:
        raise ValueError("bootstrap --force is disabled; use docs/UPGRADING.md for existing installations")
    if not target.exists() or not target.is_dir() or target.is_symlink():
        raise ValueError("bootstrap target must be an existing non-symlink directory")
    if (target / ".onecompany").exists() or (target / ".onecompany").is_symlink():
        raise ValueError("target already contains .onecompany; use the upgrade path instead")

    repo = repository or infer_github_repo(target)
    branch = default_branch or infer_default_branch(target)
    name = project_name or target.name
    owner = code_owner or "@replace-me"
    if not root_principal:
        raise ValueError("bootstrap requires --root-principal for an explicit human root identity")

    preflight_copy_paths(target)
    for item in COPY_PATHS:
        source = ROOT / item
        if source.exists():
            copy_item(source, target / item, False, target)

    config_path = target / ".onecompany" / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["project"].update({
        "name": name,
        "repository": repo or "owner/repository",
        "default_branch": branch,
    })
    config["policy"]["base_branch"] = branch
    config_path.unlink()
    write_json(config_path, config, target_root=target)

    codeowners_path = target / ".github" / "CODEOWNERS"
    lines = []
    for raw in codeowners_path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            lines.append(raw)
            continue
        path_part = stripped.split(maxsplit=1)[0]
        lines.append(f"{path_part} {owner}")
    codeowners_path.unlink()
    descriptors = [_open_root_directory(target)]
    try:
        descriptors.append(_open_directory_at(descriptors[-1], ".github", create=False))
        file_fd = os.open("CODEOWNERS", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                          mode=0o644, dir_fd=descriptors[-1])
        with os.fdopen(file_fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        for fd in reversed(descriptors):
            os.close(fd)

    principals = resolve_install_principals(root_principal)
    scrub_runtime(target, root_principal=principals["root_login"], root_actor=principals["root_actor"])
    initialize_knowledge(target)

    if initialize_contracts:
        template_dir = target / ".onecompany" / "templates"
        for template, destination in CONTRACTS.items():
            destination_path = target / destination
            if destination_path.exists() or destination_path.is_symlink():
                continue
            copy_item(template_dir / template, destination_path, False, target)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap OneCompany into a fresh repository")
    parser.add_argument("--target", required=True)
    parser.add_argument("--repository")
    parser.add_argument("--project-name")
    parser.add_argument("--default-branch")
    parser.add_argument("--code-owner")
    parser.add_argument("--root-principal", required=True)
    parser.add_argument("--initialize-contracts", action="store_true")
    parser.add_argument("--force", action="store_true", help="rejected; upgrades use docs/UPGRADING.md")
    args = parser.parse_args()
    bootstrap(
        Path(args.target).resolve(),
        repository=args.repository,
        project_name=args.project_name,
        default_branch=args.default_branch,
        code_owner=args.code_owner,
        root_principal=args.root_principal,
        initialize_contracts=args.initialize_contracts,
        force=args.force,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
