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
    "routing.json",
    "budget.json",
    "state.json",
    "queue.json",
    "patterns.json",
    "overlays.json",
    "readiness.json",
]

WRITE_CAPS = {"implementation", "ci_remediation"}
REVIEW_CAPS = {"code_review", "security_review"}
MERGE_CAPS = {"merge_execution"}


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
    routing = docs["routing.json"]
    budget = docs["budget.json"]
    state = docs["state.json"]
    queue = docs["queue.json"]
    patterns = docs["patterns.json"]
    overlays = docs["overlays.json"]
    readiness = docs["readiness.json"]

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
    conditional = set(budget.get("cost_classes", {}).get("conditionally_allowed", []))
    forbidden = set(budget.get("cost_classes", {}).get("forbidden", []))
    if allowed & forbidden:
        errors.append(f"budget cost classes both allowed and forbidden: {sorted(allowed & forbidden)}")
    if conditional & forbidden:
        errors.append(f"budget cost classes both conditional and forbidden: {sorted(conditional & forbidden)}")

    actor_ids: set[str] = set()
    actor_capabilities: dict[str, set[str]] = {}
    actor_costs: dict[str, str] = {}
    enabled_actor_ids: set[str] = set()
    declared_capability_universe: set[str] = set()
    for actor in actors.get("actors", []):
        actor_id = actor.get("id")
        if not actor_id:
            errors.append("actor missing id")
            continue
        if actor_id in actor_ids:
            errors.append(f"duplicate actor id: {actor_id}")
        actor_ids.add(actor_id)
        capabilities = set(actor.get("capabilities", []))
        actor_capabilities[actor_id] = capabilities
        declared_capability_universe.update(capabilities)
        actor_costs[actor_id] = actor.get("cost_class", "UNKNOWN_COST")
        if not capabilities:
            errors.append(f"actor {actor_id} has no capabilities")
        if actor.get("may_independently_gate_own_material_authorship") is True:
            errors.append(f"actor {actor_id} may not independently gate its own material authorship")
        if actor_costs[actor_id] not in allowed | conditional | forbidden:
            errors.append(f"actor {actor_id} uses cost class not classified by budget: {actor_costs[actor_id]}")
        if actor.get("enabled"):
            enabled_actor_ids.add(actor_id)
            if not actor.get("configured"):
                errors.append(f"actor {actor_id} is enabled but configured=false")

    readiness_by_actor: dict[str, dict] = {}
    for item in readiness.get("actors", []):
        actor_id = item.get("actor_id")
        if not actor_id:
            errors.append("readiness record missing actor_id")
            continue
        if actor_id in readiness_by_actor:
            errors.append(f"duplicate readiness actor_id: {actor_id}")
            continue
        readiness_by_actor[actor_id] = item
        if actor_id not in actor_ids:
            errors.append(f"readiness record references unknown actor: {actor_id}")
            continue

        setup_state = item.get("setup_state")
        if setup_state not in {"not_started", "partially_ready", "ready", "degraded", "unavailable"}:
            errors.append(f"readiness {actor_id} has invalid setup_state: {setup_state}")

        verified = set(item.get("verified_capabilities", []))
        unavailable = set(item.get("temporarily_unavailable_capabilities", []))
        declared = actor_capabilities.get(actor_id, set())
        if verified - declared:
            errors.append(f"readiness {actor_id} verifies undeclared capabilities: {sorted(verified - declared)}")
        if unavailable - declared:
            errors.append(f"readiness {actor_id} marks undeclared capabilities unavailable: {sorted(unavailable - declared)}")

        access = item.get("repository_access", {})
        for key in ("read", "write", "review", "merge"):
            if not isinstance(access.get(key), bool):
                errors.append(f"readiness {actor_id} repository_access.{key} must be boolean")
        if verified and not access.get("read"):
            errors.append(f"readiness {actor_id} verifies capabilities but repository read access is false")
        if verified & WRITE_CAPS and not access.get("write"):
            errors.append(f"readiness {actor_id} verifies write capabilities without repository write access")
        if verified & REVIEW_CAPS and not access.get("review"):
            errors.append(f"readiness {actor_id} verifies review capabilities without review-publish access")
        if verified & MERGE_CAPS and not access.get("merge"):
            errors.append(f"readiness {actor_id} verifies merge_execution without merge access")

        unattended = item.get("unattended", {})
        if unattended.get("verified") is True and unattended.get("configured") is not True:
            errors.append(f"readiness {actor_id} unattended.verified=true requires configured=true")

    missing_readiness = actor_ids - set(readiness_by_actor)
    if missing_readiness:
        errors.append(f"actors missing readiness records: {sorted(missing_readiness)}")

    for actor_id in enabled_actor_ids:
        item = readiness_by_actor.get(actor_id)
        if not item:
            continue
        if item.get("setup_state") not in {"ready", "degraded"}:
            errors.append(f"enabled actor {actor_id} must have readiness setup_state ready/degraded")
        if not item.get("verified_capabilities"):
            errors.append(f"enabled actor {actor_id} has no verified capabilities")
        if not item.get("repository_access", {}).get("read"):
            errors.append(f"enabled actor {actor_id} has no verified repository read access")

    routing_policy = routing.get("policy", {})
    for key in (
        "preferences_are_not_leases",
        "live_readiness_outranks_preference",
        "budget_outranks_preference",
        "reviewer_independence_outranks_preference",
        "healthy_replacement_is_not_preempted_mid_attempt",
    ):
        if routing_policy.get(key) is not True:
            errors.append(f"routing.policy.{key} must be true")

    preferences = routing.get("preference_by_capability", {})
    for capability in sorted(declared_capability_universe):
        ordered = preferences.get(capability)
        if not isinstance(ordered, list) or not ordered:
            errors.append(f"routing missing non-empty preference list for declared capability: {capability}")
            continue
        if len(ordered) != len(set(ordered)):
            errors.append(f"routing preference for {capability} contains duplicate actors")
        for actor_id in ordered:
            if actor_id not in actor_ids:
                errors.append(f"routing preference {capability} references unknown actor: {actor_id}")
            elif capability not in actor_capabilities.get(actor_id, set()):
                errors.append(f"routing preference {capability} includes actor without declared capability: {actor_id}")

    for capability in preferences:
        if capability not in declared_capability_universe:
            warnings.append(f"routing defines preference for capability no actor declares: {capability}")

    role_ids: set[str] = set()
    for role in roles.get("roles", []):
        role_id = role.get("id")
        if role_id in role_ids:
            errors.append(f"duplicate role id: {role_id}")
        role_ids.add(role_id)
        required_caps = set(role.get("required_capabilities", []))
        if not required_caps:
            warnings.append(f"role {role_id} has no required capabilities")
        elif not any(required_caps <= caps for caps in actor_capabilities.values()):
            errors.append(f"role {role_id} has no declared actor capable of all required capabilities: {sorted(required_caps)}")

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

    authors = state.get("current_material_authors", [])
    if not isinstance(authors, list) or any(not isinstance(item, str) or not item for item in authors):
        errors.append("state.current_material_authors must be an array of non-empty actor IDs")
        authors = []
    if len(authors) != len(set(authors)):
        errors.append("state.current_material_authors contains duplicates")
    for author in authors:
        if author not in actor_ids:
            errors.append(f"state.current_material_authors references unknown actor: {author}")

    impl_leases = active_implementation_leases(state)
    if len(impl_leases) > 1 and delivery.get("single_canonical_stream"):
        errors.append("state contains more than one active implementation lease")
    for lease in impl_leases:
        actor_id = lease.get("actor")
        if actor_id not in actor_ids:
            errors.append(f"active implementation lease references unknown actor: {actor_id}")
        if actor_id and actor_id not in authors:
            warnings.append(f"active implementation lease actor {actor_id} is not yet in current_material_authors")
    if config.get("no_idle", {}).get("enabled") and state.get("ready_work_count", 0) > 0 and not impl_leases:
        errors.append("FAULT_IDLE_WITH_READY_WORK: ready work exists but no active implementation lease")

    gate = state.get("current_gate")
    if gate:
        reviewer = gate.get("reviewer_actor")
        if reviewer and reviewer not in actor_ids:
            errors.append(f"current gate references unknown reviewer actor: {reviewer}")
        if reviewer and reviewer in authors:
            errors.append(f"current gate reviewer is a tracked material author: {reviewer}")
        gate_authors = gate.get("material_authors")
        if gate_authors is not None and set(gate_authors) != set(authors):
            errors.append("current gate material_authors does not match current state material authors")
        if gate.get("verdict") == "PASS — MERGE_READY":
            if gate.get("sha") != state.get("current_pr_head"):
                errors.append("current merge-ready gate SHA does not equal current PR head")
            if gate.get("stale") is True:
                errors.append("current merge-ready gate is marked stale")
            if state.get("open_blockers"):
                errors.append("current merge-ready gate exists while open blockers remain")
            if state.get("human_decision_required"):
                errors.append("current merge-ready gate exists while human decision is required")

    if state.get("current_pr") is None and state.get("current_pr_head") is not None:
        errors.append("state.current_pr_head set while state.current_pr is null")
    if state.get("current_pr") is None and gate is not None:
        errors.append("state.current_gate set while state.current_pr is null")

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
