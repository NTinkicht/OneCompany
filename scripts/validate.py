#!/usr/bin/env python3
"""Validate OneCompany control-plane JSON and core operating invariants."""
from __future__ import annotations

import sys
from pathlib import Path

from onecompany_lib import CONTROL, active_implementation_leases, autonomy_number, load_json

REQUIRED = [
    "config.json",
    "actors.json",
    "roles.json",
    "budget.json",
    "state.json",
    "queue.json",
    "patterns.json",
    "overlays.json",
]


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []
    docs: dict[str, dict] = {}
    repo_root = CONTROL.parent

    for name in REQUIRED:
        path = CONTROL / name
        if not path.exists():
            errors.append(f"missing {path.relative_to(Path.cwd()) if Path.cwd() in path.parents else path}")
            continue
        try:
            docs[name] = load_json(path)
        except Exception as exc:
            errors.append(f"{name}: invalid JSON: {exc}")

    if errors:
        return finish(errors, warnings)

    config = docs["config.json"]
    actors = docs["actors.json"]
    roles = docs["roles.json"]
    budget = docs["budget.json"]
    state = docs["state.json"]
    queue = docs["queue.json"]
    patterns = docs["patterns.json"]
    overlays = docs["overlays.json"]

    if config.get("project", {}).get("source_of_truth") != "github":
        errors.append("config.project.source_of_truth must be 'github'")

    delivery = config.get("delivery", {})
    for key in (
        "single_canonical_stream",
        "require_explicit_implementation_lease",
        "require_exact_head_gate",
        "require_independent_non_author_review",
        "require_expected_head_merge",
    ):
        if delivery.get(key) is not True:
            errors.append(f"delivery.{key} must be true in the reference operating model")

    try:
        level = autonomy_number(config.get("autonomy", {}).get("level", ""))
    except ValueError as exc:
        errors.append(str(exc))
        level = 0

    if level >= 4 and not config.get("autonomy", {}).get("continue_when_ready_work_exists"):
        errors.append("L4/L5 requires autonomy.continue_when_ready_work_exists=true")
    if level >= 4 and not config.get("no_idle", {}).get("enabled"):
        errors.append("L4/L5 requires no_idle.enabled=true")

    ai = budget.get("ai", {})
    cap = ai.get("additional_monthly_spend_cap")
    if not isinstance(cap, (int, float)) or cap < 0:
        errors.append("budget.ai.additional_monthly_spend_cap must be a non-negative number")
    if cap == 0:
        for key in ("allow_paid_fallback", "allow_overage", "allow_auto_topup", "allow_new_paid_vendor"):
            if ai.get(key):
                errors.append(f"zero-spend policy cannot set ai.{key}=true")

    allowed = set(budget.get("cost_classes", {}).get("allowed", []))
    forbidden = set(budget.get("cost_classes", {}).get("forbidden", []))
    overlap = allowed & forbidden
    if overlap:
        errors.append(f"budget cost classes both allowed and forbidden: {sorted(overlap)}")

    actor_ids: set[str] = set()
    for actor in actors.get("actors", []):
        actor_id = actor.get("id")
        if not actor_id:
            errors.append("actor missing id")
            continue
        if actor_id in actor_ids:
            errors.append(f"duplicate actor id: {actor_id}")
        actor_ids.add(actor_id)
        if not actor.get("capabilities"):
            errors.append(f"actor {actor_id} has no capabilities")
        if actor.get("may_independently_gate_own_material_authorship") is True:
            warnings.append(f"actor {actor_id} can gate own material authorship; verify this is intentional")
        if actor.get("enabled") and not actor.get("configured"):
            errors.append(f"actor {actor_id} is enabled but configured=false")

    role_ids: set[str] = set()
    for role in roles.get("roles", []):
        role_id = role.get("id")
        if role_id in role_ids:
            errors.append(f"duplicate role id: {role_id}")
        role_ids.add(role_id)
        if not role.get("required_capabilities"):
            warnings.append(f"role {role_id} has no required capabilities")

    pattern_ids: set[str] = set()
    for pattern in patterns.get("patterns", []):
        pattern_id = pattern.get("id")
        if not pattern_id:
            errors.append("pattern missing id")
            continue
        if pattern_id in pattern_ids:
            errors.append(f"duplicate pattern id: {pattern_id}")
        pattern_ids.add(pattern_id)
        if pattern.get("adoption") not in {"core", "recommended", "optional", "experimental"}:
            errors.append(f"pattern {pattern_id} has invalid adoption level")
        doc_path = repo_root / "patterns" / f"{pattern_id}.md"
        if not doc_path.exists():
            errors.append(f"pattern {pattern_id} is missing documentation at {doc_path.relative_to(repo_root)}")

    overlay_rules = overlays.get("rules", {})
    forbidden_true = (
        "creates_actor",
        "creates_capacity",
        "creates_implementation_lease",
        "grants_repository_permission",
        "overrides_material_authorship",
        "overrides_self_gate_rule",
        "grants_merge_authority",
    )
    for key in forbidden_true:
        if overlay_rules.get(key) is not False:
            errors.append(f"overlays.rules.{key} must be false")

    overlay_ids: set[str] = set()
    for overlay in overlays.get("profiles", []):
        overlay_id = overlay.get("id")
        path = overlay.get("path")
        if not overlay_id:
            errors.append("overlay missing id")
            continue
        if overlay_id in overlay_ids:
            errors.append(f"duplicate overlay id: {overlay_id}")
        overlay_ids.add(overlay_id)
        if not path:
            errors.append(f"overlay {overlay_id} missing path")
        elif not (repo_root / path).exists():
            errors.append(f"overlay {overlay_id} points to missing path {path}")

    wu_ids: set[str] = set()
    for wu in queue.get("work_units", []):
        wu_id = wu.get("id")
        if not wu_id:
            errors.append("queue work unit missing id")
            continue
        if wu_id in wu_ids:
            errors.append(f"duplicate work unit id: {wu_id}")
        wu_ids.add(wu_id)
    for wu in queue.get("work_units", []):
        for dep in wu.get("dependencies", []):
            if dep not in wu_ids:
                warnings.append(f"{wu.get('id')} depends on {dep}, which is not present in queue.json")
            if dep == wu.get("id"):
                errors.append(f"{wu.get('id')} cannot depend on itself")

    impl_leases = active_implementation_leases(state)
    if len(impl_leases) > 1 and delivery.get("single_canonical_stream"):
        errors.append("state contains more than one active implementation lease")
    if config.get("no_idle", {}).get("enabled") and state.get("ready_work_count", 0) > 0 and not impl_leases:
        errors.append("FAULT_IDLE_WITH_READY_WORK: ready work exists but no active implementation lease")

    gate = state.get("current_gate")
    if gate and gate.get("verdict") == "PASS — MERGE_READY":
        if gate.get("sha") != state.get("current_pr_head"):
            errors.append("current merge-ready gate SHA does not equal current PR head")

    if state.get("current_pr") is None and state.get("current_pr_head") is not None:
        errors.append("state.current_pr_head set while state.current_pr is null")

    return finish(errors, warnings)


def finish(errors: list[str], warnings: list[str]) -> int:
    for warning in warnings:
        print(f"WARN: {warning}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"OneCompany validation FAILED ({len(errors)} error(s), {len(warnings)} warning(s)).")
        return 1
    print(f"OneCompany validation PASS ({len(warnings)} warning(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
