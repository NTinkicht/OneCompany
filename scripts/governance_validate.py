#!/usr/bin/env python3
"""Validate OneCompany fail-closed governance invariants."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

from onecompany_lib import CONTROL, ROOT, load_json, path_matches_any


def command_scripts() -> set[str]:
    tree = ast.parse((ROOT / "onecompany.py").read_text(encoding="utf-8"))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "COMMANDS" and isinstance(node.value, ast.Dict):
                    for value in node.value.values:
                        if isinstance(value, ast.Constant) and isinstance(value.value, str):
                            result.add(f"scripts/{value.value}")
    return result


def executable_control_plane_paths() -> set[str]:
    """Return every repository path that the managed CI may import/run/compile."""
    result = {"onecompany.py"}
    scripts = ROOT / "scripts"
    if scripts.exists():
        result.update(path.relative_to(ROOT).as_posix() for path in scripts.rglob("*.py") if path.is_file())
    selftests = CONTROL / "selftest"
    if selftests.exists():
        result.update(path.relative_to(ROOT).as_posix() for path in selftests.rglob("*.py") if path.is_file())
    return result


def main() -> int:
    errors: list[str] = []
    try:
        governance = load_json(CONTROL / "governance.json")
        config = load_json(CONTROL / "config.json")
        actors = load_json(CONTROL / "actors.json")
        budget = load_json(CONTROL / "budget.json")
    except Exception as exc:
        print(f"ERROR: cannot load governance inputs: {exc}")
        return 1

    control = governance.get("control_plane", {})
    if not isinstance(control.get("human_merge_required"), bool):
        errors.append("control_plane.human_merge_required must be boolean")
    for key in (
        "independent_non_author_technical_review_required",
        "exact_head_ci_required",
        "expected_head_merge_required",
        "fail_closed_if_diff_unavailable",
    ):
        if control.get(key) is not True:
            errors.append(f"control_plane.{key} must be true")
    protected = list(control.get("protected_paths", []))
    always_human = list(control.get("always_human_paths", []))
    for required in {"company/CONSTITUTION.md", ".onecompany/governance.json"}:
        if not path_matches_any(required, always_human):
            errors.append(f"always_human_paths must protect {required}")

    for script in sorted(command_scripts()):
        if not path_matches_any(script, protected):
            errors.append(f"CLI control-plane script is not protected from autonomous merge: {script}")
    for path in sorted(executable_control_plane_paths()):
        if not path_matches_any(path, protected):
            errors.append(f"CI-executable control-plane path is outside protected governance: {path}")

    structural_expectations = {
        ".onecompany/selftest/new_test.py",
        "scripts/new_helper.py",
        "company/new_kernel_policy.md",
        ".github/workflows/new-workflow.yml",
    }
    for path in sorted(structural_expectations):
        if not path_matches_any(path, protected):
            errors.append(f"protected_paths must structurally cover future control-plane path: {path}")

    codeowners = ROOT / ".github" / "CODEOWNERS"
    if not codeowners.exists():
        errors.append(".github/CODEOWNERS is required for protected CompanyOS surfaces")

    policy = governance.get("policy", {})
    for key in ("no_self_escalation", "control_plane_relaxation_requires_human", "ambiguity_fails_closed"):
        if policy.get(key) is not True:
            errors.append(f"governance.policy.{key} must be true")
    supply = governance.get("supply_chain", {})
    for key in (
        "all_workflow_actions_require_sha_pin",
        "forbid_pull_request_target_in_all_workflows",
        "forbid_write_all_in_all_workflows",
    ):
        if supply.get(key) is not True:
            errors.append(f"governance.supply_chain.{key} must be true")
    side = governance.get("side_effects", {})
    for key in (
        "require_idempotency_or_natural_deduplication",
        "require_rollback_or_compensation_for_destructive_actions",
        "require_bounded_retry_policy",
    ):
        if side.get(key) is not True:
            errors.append(f"governance.side_effects.{key} must be true")

    safety = config.get("safety", {})
    for key in (
        "fail_closed_on_ambiguous_authority",
        "external_side_effects_require_idempotency",
        "destructive_change_requires_recovery_plan",
    ):
        if safety.get(key) is not True:
            errors.append(f"config.safety.{key} must be true")
    if not isinstance(safety.get("emergency_stop"), bool):
        errors.append("config.safety.emergency_stop must be boolean")
    human_only = set(config.get("human_only_decisions", []))
    for item in {
        "increase_autonomy_level",
        "change_budget_policy",
        "add_or_expand_credentials",
        "amend_company_constitution",
        "relax_control_plane_guardrails",
    }:
        if item not in human_only:
            errors.append(f"human_only_decisions must contain {item}")

    human = next((item for item in actors.get("actors", []) if item.get("id") == "human-owner"), None)
    if not human:
        errors.append("actors.json must contain human-owner")
    elif human.get("cost_class") != "HUMAN":
        errors.append("human-owner must use HUMAN cost class")
    if "HUMAN" not in set(budget.get("cost_classes", {}).get("allowed", [])):
        errors.append("budget must classify HUMAN as allowed")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"Governance validation FAILED ({len(errors)} error(s)).")
        return 1
    print("Governance validation PASS.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
