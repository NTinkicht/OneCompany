#!/usr/bin/env python3
"""One-shot, human-authorized L5 v1.1 hardening patch.

This script is intentionally deleted by the one-shot workflow after it applies
its deterministic edits. It never touches main directly.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, got {count}: {old[:80]!r}")
    write(path, text.replace(old, new, 1))


def replace_between(path: str, start: str, end: str, replacement: str) -> None:
    text = read(path)
    i = text.find(start)
    if i < 0:
        raise RuntimeError(f"{path}: start marker not found: {start!r}")
    j = text.find(end, i)
    if j < 0:
        raise RuntimeError(f"{path}: end marker not found: {end!r}")
    write(path, text[:i] + replacement + text[j:])


# ---------------------------------------------------------------------------
# Kernel: first-class intent/restraint evidence and correct pre-lock classify.
# ---------------------------------------------------------------------------
replace_once(
    "scripts/l5_kernel.py",
    '    CI_GREEN_UNREVIEWED = "CI_GREEN_UNREVIEWED"\n    FINDINGS_OPEN = "FINDINGS_OPEN"\n',
    '    CI_GREEN_UNREVIEWED = "CI_GREEN_UNREVIEWED"\n'
    '    INTENT_RESTRAINT_PENDING = "INTENT_RESTRAINT_PENDING"\n'
    '    INTENT_RESTRAINT_FAILED = "INTENT_RESTRAINT_FAILED"\n'
    '    FINDINGS_OPEN = "FINDINGS_OPEN"\n',
)

kernel = read("scripts/l5_kernel.py")
if "def intent_restraint_status(" not in kernel:
    helper = r'''
INTENT_RESTRAINT_REASON_CODES = frozenset(
    {
        "INTENT_DRIFT",
        "OVERENGINEERED",
        "DUPLICATED_MECHANISM",
        "PERFORMANCE_REGRESSION",
        "SEMANTIC_CHANGE",
        "DIFF_DISPROPORTIONATE",
        "CONVENTION_DRIFT",
        "ARCHITECTURE_DRIFT",
        "UNRESOLVED_DELETION_CANDIDATES",
        "SELF_REVIEW",
        "ATTESTATION_INCOMPLETE",
    }
)


def intent_restraint_status(snapshot: Mapping[str, Any]) -> tuple[str, tuple[str, ...]]:
    """Validate a structured, independent engineering-intent attestation.

    The attestation is bound to the exact head, base, and frozen work-unit body
    hash. Model prose is never accepted as gate evidence.
    """
    evidence = snapshot.get("intent_restraint")
    if evidence is None:
        return "PENDING", ("INTENT_RESTRAINT_MISSING",)
    if not isinstance(evidence, Mapping):
        return "FAILED", ("ATTESTATION_INCOMPLETE",)
    state = evidence.get("state")
    if state == "PENDING":
        return "PENDING", ("INTENT_RESTRAINT_PENDING",)
    if state != "PASS":
        reasons = evidence.get("failure_reasons")
        if not isinstance(reasons, list) or not reasons:
            return "FAILED", ("ATTESTATION_INCOMPLETE",)
        normalized = tuple(str(reason) for reason in reasons)
        if any(reason not in INTENT_RESTRAINT_REASON_CODES for reason in normalized):
            return "FAILED", ("ATTESTATION_INCOMPLETE",)
        return "FAILED", normalized

    head = snapshot.get("head_sha")
    base = snapshot.get("base_sha")
    wu_hash = snapshot.get("wu_body_hash")
    failures: list[str] = []
    if not _sha(head) or evidence.get("head_sha") != head:
        failures.append("INTENT_DRIFT")
    if not _sha(base) or evidence.get("base_sha") != base:
        failures.append("INTENT_DRIFT")
    if not isinstance(wu_hash, str) or not wu_hash or evidence.get("wu_body_hash") != wu_hash:
        failures.append("INTENT_DRIFT")
    if evidence.get("material_authors_head_sha") != head:
        failures.append("INTENT_DRIFT")

    required_true = {
        "complete": "ATTESTATION_INCOMPLETE",
        "designated_independent": "SELF_REVIEW",
        "reviewer_eligible": "SELF_REVIEW",
        "identity_source_verified": "ATTESTATION_INCOMPLETE",
        "wu_contract_frozen": "INTENT_DRIFT",
        "intent_preserved": "INTENT_DRIFT",
        "scope_discipline_verified": "INTENT_DRIFT",
        "minimal_change_verified": "OVERENGINEERED",
        "no_overengineering": "OVERENGINEERED",
        "existing_mechanism_reused_or_justified": "DUPLICATED_MECHANISM",
        "conventions_preserved": "CONVENTION_DRIFT",
        "architecture_consistent": "ARCHITECTURE_DRIFT",
        "performance_preserved": "PERFORMANCE_REGRESSION",
        "api_semantics_preserved": "SEMANTIC_CHANGE",
        "diff_proportionate": "DIFF_DISPROPORTIONATE",
        "adversarial_deletion_review_complete": "ATTESTATION_INCOMPLETE",
        "deletion_candidates_resolved": "UNRESOLVED_DELETION_CANDIDATES",
    }
    for key, reason in required_true.items():
        if evidence.get(key) is not True:
            failures.append(reason)

    reasons = evidence.get("failure_reasons")
    if reasons != []:
        failures.append("ATTESTATION_INCOMPLETE")

    reviewer = evidence.get("author")
    authors = evidence.get("material_authors")
    controllers = evidence.get("controller_identities")
    if not isinstance(reviewer, str) or not reviewer.strip():
        failures.append("ATTESTATION_INCOMPLETE")
    elif not isinstance(authors, list) or not isinstance(controllers, list):
        failures.append("ATTESTATION_INCOMPLETE")
    else:
        norm = reviewer.strip().lower()
        excluded = {str(actor).strip().lower() for actor in authors + controllers}
        if norm in excluded:
            failures.append("SELF_REVIEW")

    unique = tuple(dict.fromkeys(failures))
    return ("PASS", ()) if not unique else ("FAILED", unique)


def intent_restraint_ok(snapshot: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Return a fail-closed boolean view of the intent/restraint gate."""
    state, reasons = intent_restraint_status(snapshot)
    return state == "PASS", reasons


def merge_ok_v11(snapshot: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Evaluate base MERGE_OK plus the L5.1 Engineering Intent & Restraint gate."""
    base_ok, base_failures = merge_ok(snapshot)
    if snapshot.get("l5_intent_restraint_required") is not True:
        return base_ok, base_failures
    restraint_ok, restraint_failures = intent_restraint_ok(snapshot)
    failures = tuple(base_failures) + tuple(restraint_failures)
    return base_ok and restraint_ok, failures


def merge_precheck_v11(snapshot: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Evaluate merge readiness before runtime-only lock/fence acquisition."""
    staged = dict(snapshot)
    staged["merge_lock_owned"] = True
    staged["fence_ok"] = True
    staged["unresolved_other_intent"] = False
    return merge_ok_v11(staged)

'''
    kernel = kernel.replace("\nTRUE_FIELDS = (\n", "\n" + helper + "\nTRUE_FIELDS = (\n", 1)
    write("scripts/l5_kernel.py", kernel)

replace_once(
    "scripts/l5_kernel.py",
    '    if snapshot.get("independent_review_pass") is not True:\n        return ItemState.CI_GREEN_UNREVIEWED\n    return ItemState.MERGE_ELIGIBLE if merge_ok(snapshot)[0] else ItemState.FINDINGS_OPEN\n',
    '    if snapshot.get("independent_review_pass") is not True:\n'
    '        return ItemState.CI_GREEN_UNREVIEWED\n'
    '    if snapshot.get("l5_intent_restraint_required") is True:\n'
    '        restraint_state, _ = intent_restraint_status(snapshot)\n'
    '        if restraint_state == "PENDING":\n'
    '            return ItemState.INTENT_RESTRAINT_PENDING\n'
    '        if restraint_state != "PASS":\n'
    '            return ItemState.INTENT_RESTRAINT_FAILED\n'
    '        ok, failures = merge_precheck_v11(snapshot)\n'
    '    else:\n'
    '        staged = dict(snapshot)\n'
    '        staged["merge_lock_owned"] = True\n'
    '        staged["fence_ok"] = True\n'
    '        staged["unresolved_other_intent"] = False\n'
    '        ok, failures = merge_ok(staged)\n'
    '    if ok:\n'
    '        return ItemState.MERGE_ELIGIBLE\n'
    '    finding_codes = {\n'
    '        "FINDINGS_CONFIRMED_CLOSED_NOT_TRUE",\n'
    '        "UNRESOLVED_REQUIRED_THREADS_NOT_FALSE",\n'
    '        "THREAD_RESOLUTION_POLICY_OK_NOT_TRUE",\n'
    '    }\n'
    '    if failures and set(failures).issubset(finding_codes):\n'
    '        return ItemState.FINDINGS_OPEN\n'
    '    return ItemState.BLOCK_HUMAN\n',
)

# ---------------------------------------------------------------------------
# Ledger: a PENDING intent is immutable except for its terminal state.
# ---------------------------------------------------------------------------
replace_once(
    "scripts/l5_ledger.py",
    '        if next_intent.get("op_id") != cur_intent.get("op_id"):\n'
    '            raise LedgerConflict("PENDING_INTENT_REPLACED")\n'
    '        if next_intent.get("state") not in {"PENDING", "DONE", "ABORTED"}:\n',
    '        if next_intent.get("op_id") != cur_intent.get("op_id"):\n'
    '            raise LedgerConflict("PENDING_INTENT_REPLACED")\n'
    '        for field in ("idem_key", "operation", "expected_head", "expected_base", "epoch"):\n'
    '            if next_intent.get(field) != cur_intent.get(field):\n'
    '                raise LedgerConflict("PENDING_INTENT_MUTATED")\n'
    '        if next_intent.get("state") not in {"PENDING", "DONE", "ABORTED"}:\n',
)

# ---------------------------------------------------------------------------
# Activation: behind-base update is now an explicit authorized operation.
# Revert remains outside normal autonomous selection until a dedicated recovery
# authorization contract exists.
# ---------------------------------------------------------------------------
replace_once(
    "scripts/l5_activation.py",
    '    "PLAN_REPLENISH_READY_WU": "reserve_next_wu",\n',
    '    "PLAN_REPLENISH_READY_WU": "reserve_next_wu",\n'
    '    "RECONCILE_HEAD_BASE": "update_branch",\n',
)

# ---------------------------------------------------------------------------
# Controller: correct pre-lock classification, fresh final merge authorization,
# abort no-write intents, cooldown blocked actions, and expose the correct bridge
# method name.
# ---------------------------------------------------------------------------
replace_once(
    "scripts/l5_controller.py",
    '    intent_recovery,\n    lease_key,\n    merge_ok,\n',
    '    intent_recovery,\n    intent_restraint_status,\n    lease_key,\n    merge_ok,\n    merge_ok_v11,\n    merge_precheck_v11,\n',
)

replace_once(
    "scripts/l5_controller.py",
    '        ItemState.CI_GREEN_UNREVIEWED: 6,\n        ItemState.MERGE_ELIGIBLE: 7,\n        ItemState.IMPLEMENT: 8,\n        ItemState.IDLE: 9,\n',
    '        ItemState.CI_GREEN_UNREVIEWED: 6,\n'
    '        ItemState.INTENT_RESTRAINT_FAILED: 7,\n'
    '        ItemState.INTENT_RESTRAINT_PENDING: 8,\n'
    '        ItemState.MERGE_ELIGIBLE: 9,\n'
    '        ItemState.IMPLEMENT: 10,\n'
    '        ItemState.IDLE: 11,\n',
)

replace_once(
    "scripts/l5_controller.py",
    '    if state == ItemState.BEHIND_BASE:\n        return "update_branch"\n'
    '    if state == ItemState.MERGE_ELIGIBLE:\n        return "merge_expected_head"\n'
    '    if state == ItemState.MAIN_BROKEN:\n        return "revert"\n',
    '    if state == ItemState.BEHIND_BASE:\n'
    '        return "update_branch"\n'
    '    if state == ItemState.MERGE_ELIGIBLE:\n'
    '        return "merge_expected_head"\n'
    '    # MAIN_BROKEN requires its own independently authorized recovery path.\n'
    '    # Do not repeatedly select an operation the guarded bridge cannot authorize.\n',
)

new_select = r'''def _select(
    repo_id: str,
    io: ControllerIO,
    store: CASStore,
    items: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ItemState] | None:
    """Classify and select one actionable item, skipping active cooldown leases."""
    candidates: list[tuple[int, str, Mapping[str, Any], ItemState]] = []
    now = _trusted_now(io)
    for raw in items:
        item = dict(raw)
        item["l5_intent_restraint_required"] = True
        state = classify_item(item, io.budget_for(item))
        operation = _operation_for(state, item)
        if operation is None:
            continue
        key = _lease_key_for(repo_id, _item_id(item), operation, item)
        current = store.read(key)
        if current is not None and current.expires_at > now:
            continue
        candidates.append((_state_priority(state), _item_id(item), item, state))
    if not candidates:
        return None
    candidates.sort(key=lambda row: (row[0], row[1]))
    _, _, item, state = candidates[0]
    return item, state


'''
replace_between(
    "scripts/l5_controller.py",
    "def _select(\n",
    "def _find_merged_unverified(\n",
    new_select,
)

new_revalidate = r'''def _revalidate_before_write(
    repo_id: str,
    io: ControllerIO,
    store: CASStore,
    operation: str,
    original: Mapping[str, Any],
    expected_observation: Observation,
) -> tuple[Mapping[str, Any] | None, str | None]:
    """Refresh complete evidence immediately before a material write."""
    fresh_repo = io.repo_snapshot()
    derived = governance_mode(fresh_repo)
    current_mode, _ = store.read_repo_mode(repo_id)
    allowed_mode = RepoMode.MAIN_BROKEN if operation == "revert" else RepoMode.NORMAL
    if derived != allowed_mode or current_mode != allowed_mode:
        return None, f"REPO_MODE_{derived.value}"

    fresh = dict(io.refresh_item(original))
    fresh["l5_intent_restraint_required"] = True
    if _item_id(fresh) != _item_id(original):
        return None, "ITEM_ID_CHANGED"
    if io.observe_item(fresh) != expected_observation:
        return None, "OBSERVATION_CHANGED"
    if operation == "merge_expected_head" and not merge_precheck_v11(fresh)[0]:
        return None, "MERGE_OK_FALSE_FINAL"
    return fresh, None


'''
replace_between(
    "scripts/l5_controller.py",
    "def _revalidate_before_write(\n",
    "def _terminalize_non_main_write(\n",
    new_revalidate,
)

replace_once(
    "scripts/l5_controller.py",
    "    selected = _select(io, items)\n",
    "    selected = _select(repo_id, io, store, items)\n",
)
replace_once(
    "scripts/l5_controller.py",
    '    if operation == "merge_expected_head" and not merge_ok(item)[0]:\n',
    '    if operation == "merge_expected_head" and not merge_precheck_v11(item)[0]:\n',
)

replace_once(
    "scripts/l5_controller.py",
    '    if final_item is None:\n'
    '        return RunResult(\n'
    '            rid,\n'
    '            RunPhase.FENCE_CHECK,\n'
    '            "BLOCKED",\n'
    '            action=operation,\n'
    '            item_id=item_id,\n'
    '            reason=reason,\n'
    '        )\n\n'
    '    observed_final = io.observe_item(final_item)\n',
    '    if final_item is None:\n'
    '        if resolve_intent(store, with_intent, "ABORTED") is None:\n'
    '            return RunResult(rid, RunPhase.FENCE_CHECK, "WAIT", action=operation, item_id=item_id, reason="INTENT_ABORT_CAS_FAILED")\n'
    '        return RunResult(\n'
    '            rid,\n'
    '            RunPhase.FENCE_CHECK,\n'
    '            "BLOCKED",\n'
    '            action=operation,\n'
    '            item_id=item_id,\n'
    '            reason=reason,\n'
    '        )\n\n'
    '    observed_final = io.observe_item(final_item)\n',
)

replace_once(
    "scripts/l5_controller.py",
    '    if not ok:\n'
    '        return RunResult(\n'
    '            rid,\n'
    '            RunPhase.FENCE_CHECK,\n'
    '            "BLOCKED",\n'
    '            action=operation,\n'
    '            item_id=item_id,\n'
    '            reason=fence_reason,\n'
    '        )\n\n'
    '    mutation = io.execute_guarded(operation, final_item, with_intent)\n',
    '    if not ok:\n'
    '        if fence_reason not in {"LEASE_LOST", "LEASE_MISSING"}:\n'
    '            resolve_intent(store, with_intent, "ABORTED")\n'
    '        return RunResult(\n'
    '            rid,\n'
    '            RunPhase.FENCE_CHECK,\n'
    '            "BLOCKED",\n'
    '            action=operation,\n'
    '            item_id=item_id,\n'
    '            reason=fence_reason,\n'
    '        )\n\n'
    '    if operation == "merge_expected_head":\n'
    '        final_merge = dict(io.refresh_item(final_item))\n'
    '        final_merge["l5_intent_restraint_required"] = True\n'
    '        if _item_id(final_merge) != item_id or io.observe_item(final_merge) != observed:\n'
    '            resolve_intent(store, with_intent, "ABORTED")\n'
    '            return RunResult(rid, RunPhase.FENCE_CHECK, "BLOCKED", action=operation, item_id=item_id, reason="OBSERVATION_CHANGED")\n'
    '        final_repo = io.repo_snapshot()\n'
    '        final_mode, _ = store.read_repo_mode(repo_id)\n'
    '        final_merge["merge_lock_owned"] = True\n'
    '        final_merge["fence_ok"] = True\n'
    '        final_merge["unresolved_other_intent"] = False\n'
    '        final_merge["repo_mode"] = final_mode.value\n'
    '        if governance_mode(final_repo) != RepoMode.NORMAL or not merge_ok_v11(final_merge)[0]:\n'
    '            resolve_intent(store, with_intent, "ABORTED")\n'
    '            return RunResult(rid, RunPhase.FENCE_CHECK, "BLOCKED", action=operation, item_id=item_id, reason="MERGE_OK_FALSE_FINAL")\n'
    '        final_item = final_merge\n\n'
    '    mutation = io.execute_guarded(operation, final_item, with_intent)\n',
)

replace_once(
    "scripts/l5_controller.py",
    '    if status in {"FAILED", "BLOCKED"}:\n'
    '        terminal, terminal_reason = _terminalize_non_main_write(\n'
    '            io,\n'
    '            store,\n'
    '            with_intent,\n'
    '            state="ABORTED",\n'
    '        )\n'
    '        if not terminal:\n'
    '            return RunResult(\n'
    '                rid,\n'
    '                RunPhase.ACTION,\n'
    '                "WAIT",\n'
    '                action=operation,\n'
    '                item_id=item_id,\n'
    '                reason=terminal_reason,\n'
    '                mutation_result=mutation,\n'
    '            )\n'
    '        return RunResult(\n'
    '            rid,\n'
    '            RunPhase.EXIT,\n'
    '            status,\n'
    '            action=operation,\n'
    '            item_id=item_id,\n'
    '            mutation_result=mutation,\n'
    '        )\n',
    '    if status == "BLOCKED":\n'
    '        # Abort the no-write intent but deliberately retain the live lease as\n'
    '        # a bounded cooldown. _select skips active leases, so one bad item\n'
    '        # cannot starve lower-priority work on subsequent invocations.\n'
    '        if resolve_intent(store, with_intent, "ABORTED") is None:\n'
    '            return RunResult(rid, RunPhase.ACTION, "WAIT", action=operation, item_id=item_id, reason="INTENT_ABORT_CAS_FAILED", mutation_result=mutation)\n'
    '        return RunResult(rid, RunPhase.EXIT, "BLOCKED", action=operation, item_id=item_id, reason=result_reason or "ACTION_BLOCKED_COOLDOWN", mutation_result=mutation)\n\n'
    '    if status == "FAILED":\n'
    '        terminal, terminal_reason = _terminalize_non_main_write(\n'
    '            io, store, with_intent, state="ABORTED"\n'
    '        )\n'
    '        if not terminal:\n'
    '            return RunResult(rid, RunPhase.ACTION, "WAIT", action=operation, item_id=item_id, reason=terminal_reason, mutation_result=mutation)\n'
    '        return RunResult(rid, RunPhase.EXIT, status, action=operation, item_id=item_id, mutation_result=mutation)\n',
)

replace_once(
    "scripts/l5_controller.py",
    "    def execute(\n",
    "    def execute_guarded(\n",
)
replace_once(
    "scripts/l5_controller.py",
    '            "remediate_review": "remediate_review",\n'
    '            "merge_expected_head": "merge_expected_head",\n',
    '            "remediate_review": "remediate_review",\n'
    '            "update_branch": "update_branch",\n'
    '            "merge_expected_head": "merge_expected_head",\n',
)

# ---------------------------------------------------------------------------
# Controller tests: merge fixtures now carry exact-head/base/WU restraint PASS.
# ---------------------------------------------------------------------------
controller_tests = read("tests/test_l5_controller.py")
if "def intent_restraint_evidence(" not in controller_tests:
    marker = "\n\ndef merge_item():\n"
    helper = r'''

def intent_restraint_evidence(head: str, base: str, wu_hash: str) -> dict:
    """Return a valid exact-state Engineering Intent & Restraint attestation."""
    return {
        "state": "PASS",
        "head_sha": head,
        "base_sha": base,
        "wu_body_hash": wu_hash,
        "complete": True,
        "designated_independent": True,
        "reviewer_eligible": True,
        "identity_source_verified": True,
        "wu_contract_frozen": True,
        "intent_preserved": True,
        "scope_discipline_verified": True,
        "minimal_change_verified": True,
        "no_overengineering": True,
        "existing_mechanism_reused_or_justified": True,
        "conventions_preserved": True,
        "architecture_consistent": True,
        "performance_preserved": True,
        "api_semantics_preserved": True,
        "diff_proportionate": True,
        "adversarial_deletion_review_complete": True,
        "deletion_candidates_resolved": True,
        "failure_reasons": [],
        "author": "coderabbitai",
        "material_authors": ["chatgpt"],
        "controller_identities": ["controller-1", "controller-2"],
        "material_authors_head_sha": head,
    }
'''
    if marker not in controller_tests:
        raise RuntimeError("controller test merge_item marker missing")
    controller_tests = controller_tests.replace(marker, helper + marker, 1)
    write("tests/test_l5_controller.py", controller_tests)

replace_once(
    "tests/test_l5_controller.py",
    '        "review": review,\n        "ci": "GREEN",\n        "independent_review_pass": True,\n',
    '        "review": review,\n'
    '        "ci": "GREEN",\n'
    '        "independent_review_pass": True,\n'
    '        "wu_body_hash": "wu-7",\n'
    '        "l5_intent_restraint_required": True,\n'
    '        "intent_restraint": intent_restraint_evidence(head, base, "wu-7"),\n',
)

# ---------------------------------------------------------------------------
# New focused regression suite for L5.1.
# ---------------------------------------------------------------------------
write(
    "tests/test_l5_intent_restraint.py",
    r'''#!/usr/bin/env python3
"""L5.1 Engineering Intent & Restraint gate regressions."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from l5_kernel import Budget, ItemState, intent_restraint_status, merge_ok_v11, TRUE_FIELDS, FALSE_FIELDS


def attestation(head="a" * 40, base="b" * 40, wu="wu-1"):
    return {
        "state": "PASS", "head_sha": head, "base_sha": base, "wu_body_hash": wu,
        "complete": True, "designated_independent": True, "reviewer_eligible": True,
        "identity_source_verified": True, "wu_contract_frozen": True,
        "intent_preserved": True, "scope_discipline_verified": True,
        "minimal_change_verified": True, "no_overengineering": True,
        "existing_mechanism_reused_or_justified": True, "conventions_preserved": True,
        "architecture_consistent": True, "performance_preserved": True,
        "api_semantics_preserved": True, "diff_proportionate": True,
        "adversarial_deletion_review_complete": True, "deletion_candidates_resolved": True,
        "failure_reasons": [], "author": "independent-reviewer",
        "material_authors": ["chatgpt"], "controller_identities": ["controller-1"],
        "material_authors_head_sha": head,
    }


def merge_snapshot():
    head, base = "a" * 40, "b" * 40
    src = {"app_id": 1, "workflow_path": "ci.yml"}
    secsrc = {"app_id": 2, "workflow_path": "security.yml"}
    row = {
        "head_sha": head, "tested_base_sha": base, "latest_attempt": True,
        "conclusion": "success", "app_id": 1, "workflow_path": "ci.yml",
        "assertion_failure_any_attempt": False, "attempt_history_complete": True,
        "source_verified": True,
    }
    sec = {**row, "app_id": 2, "workflow_path": "security.yml"}
    review = {
        "state": "APPROVED", "commit_id": head, "base_sha": base, "complete": True,
        "skipped": False, "covers_full_diff": True, "author": "independent-reviewer",
        "material_authors": ["chatgpt"], "controller_identities": ["controller-1"],
        "designated_independent": True, "reviewer_eligible": True, "authorship_complete": True,
        "material_authors_head_sha": head, "identity_source_verified": True,
    }
    snap = {
        "head_sha": head, "base_sha": base, "expected_head_sha": head,
        "expected_base_sha": base, "repo_mode": "NORMAL", "required_checks": [row],
        "required_check_sources": [src], "security_checks": [sec],
        "security_check_sources": [secsrc], "review": review, "ci": "GREEN",
        "independent_review_pass": True, "wu_body_hash": "wu-1",
        "l5_intent_restraint_required": True, "intent_restraint": attestation(),
    }
    for key in TRUE_FIELDS: snap[key] = True
    for key in FALSE_FIELDS: snap[key] = False
    return snap


class IntentRestraintTests(unittest.TestCase):
    def test_pass_is_exact_state_bound(self):
        snap = merge_snapshot()
        self.assertEqual(intent_restraint_status(snap), ("PASS", ()))
        self.assertEqual(merge_ok_v11(snap), (True, ()))

    def test_missing_attestation_is_pending(self):
        snap = merge_snapshot(); snap.pop("intent_restraint")
        self.assertEqual(intent_restraint_status(snap)[0], "PENDING")
        self.assertFalse(merge_ok_v11(snap)[0])

    def test_head_base_and_wu_drift_fail(self):
        for field, value in (("head_sha", "c" * 40), ("base_sha", "d" * 40), ("wu_body_hash", "other")):
            snap = merge_snapshot(); snap["intent_restraint"] = dict(snap["intent_restraint"]); snap["intent_restraint"][field] = value
            self.assertEqual(intent_restraint_status(snap)[0], "FAILED")

    def test_self_review_fails(self):
        snap = merge_snapshot(); snap["intent_restraint"] = dict(snap["intent_restraint"]); snap["intent_restraint"]["author"] = "chatgpt"
        self.assertIn("SELF_REVIEW", intent_restraint_status(snap)[1])

    def test_engineering_regressions_fail(self):
        cases = {
            "no_overengineering": "OVERENGINEERED",
            "existing_mechanism_reused_or_justified": "DUPLICATED_MECHANISM",
            "performance_preserved": "PERFORMANCE_REGRESSION",
            "api_semantics_preserved": "SEMANTIC_CHANGE",
            "diff_proportionate": "DIFF_DISPROPORTIONATE",
        }
        for field, reason in cases.items():
            snap = merge_snapshot(); snap["intent_restraint"] = dict(snap["intent_restraint"]); snap["intent_restraint"][field] = False
            self.assertIn(reason, intent_restraint_status(snap)[1])

    def test_classifier_exposes_pending_and_failed_states(self):
        pending = {"ci": "GREEN", "independent_review_pass": True, "l5_intent_restraint_required": True}
        self.assertEqual(classify(pending), ItemState.INTENT_RESTRAINT_PENDING)
        failed = dict(pending); failed["head_sha"] = "a" * 40; failed["base_sha"] = "b" * 40; failed["wu_body_hash"] = "wu"; failed["intent_restraint"] = {"state": "FAIL", "failure_reasons": ["OVERENGINEERED"]}
        self.assertEqual(classify(failed), ItemState.INTENT_RESTRAINT_FAILED)


def classify(snapshot):
    from l5_kernel import classify_item
    return classify_item(snapshot, Budget())


if __name__ == "__main__": unittest.main()
''',
)

# ---------------------------------------------------------------------------
# S31-S40: additional hostile traces dedicated to intent/restraint integrity.
# ---------------------------------------------------------------------------
write(
    "scripts/l5_intent_hostile_sim.py",
    r'''#!/usr/bin/env python3
"""L5.1 hostile certification scenarios S31-S40 (10,000 traces)."""
from __future__ import annotations

import random
from l5_kernel import intent_restraint_status

HEX = "0123456789abcdef"


def valid(rng: random.Random):
    h = rng.choice(HEX) * 40
    b = rng.choice(HEX) * 40
    if b == h: b = ("f" if h[0] != "f" else "e") * 40
    wu = f"wu-{rng.randrange(1_000_000_000)}"
    evidence = {
        "state": "PASS", "head_sha": h, "base_sha": b, "wu_body_hash": wu,
        "complete": True, "designated_independent": True, "reviewer_eligible": True,
        "identity_source_verified": True, "wu_contract_frozen": True,
        "intent_preserved": True, "scope_discipline_verified": True,
        "minimal_change_verified": True, "no_overengineering": True,
        "existing_mechanism_reused_or_justified": True, "conventions_preserved": True,
        "architecture_consistent": True, "performance_preserved": True,
        "api_semantics_preserved": True, "diff_proportionate": True,
        "adversarial_deletion_review_complete": True, "deletion_candidates_resolved": True,
        "failure_reasons": [], "author": "external-reviewer",
        "material_authors": ["chatgpt"], "controller_identities": ["controller"],
        "material_authors_head_sha": h,
    }
    return {"head_sha": h, "base_sha": b, "wu_body_hash": wu, "intent_restraint": evidence}


def scenario(sid: int, rng: random.Random):
    snap = valid(rng); ev = dict(snap["intent_restraint"]); snap["intent_restraint"] = ev
    if sid == 31: ev["head_sha"] = rng.choice(HEX) * 40
    elif sid == 32: ev["base_sha"] = rng.choice(HEX) * 40
    elif sid == 33: ev["wu_body_hash"] = "mutated-" + snap["wu_body_hash"]
    elif sid == 34: ev["author"] = rng.choice(ev["material_authors"] + ev["controller_identities"])
    elif sid == 35: ev[rng.choice(["minimal_change_verified", "no_overengineering"])] = False
    elif sid == 36: ev["performance_preserved"] = False
    elif sid == 37: ev["api_semantics_preserved"] = False
    elif sid == 38: ev["diff_proportionate"] = False
    elif sid == 39: ev["deletion_candidates_resolved"] = False
    elif sid == 40: ev["failure_reasons"] = [rng.choice(["OVERENGINEERED", "INTENT_DRIFT", "PERFORMANCE_REGRESSION"])]
    else: raise AssertionError(sid)
    state, reasons = intent_restraint_status(snap)
    assert state == "FAILED" and reasons, (sid, state, reasons)


def run(rounds=1000, seed=0x51A11):
    rng = random.Random(seed); counts = {}; order = list(range(31, 41))
    for _ in range(rounds):
        rng.shuffle(order)
        for sid in order:
            scenario(sid, rng); counts[f"S{sid}"] = counts.get(f"S{sid}", 0) + 1
    return counts


def selftest():
    counts = run(); assert len(counts) == 10; assert all(v == 1000 for v in counts.values())
    print("l5_intent_hostile_sim PASS", counts)


if __name__ == "__main__": selftest()
''',
)

# ---------------------------------------------------------------------------
# Contract extension and candidate CI.
# ---------------------------------------------------------------------------
write(
    "docs/L5-INTENT-RESTRAINT-V1.1.md",
    r'''# L5.1 Engineering Intent & Restraint Gate

## Invariant

Prefer the smallest maintainable correct change that satisfies the frozen work-unit intent while preserving repository conventions, architecture, semantics, and performance.

A green CI run and a technically positive review are necessary but not sufficient for autonomous merge.

## Lifecycle

`IMPLEMENTED -> TESTED -> REVIEWED -> INTENT_RESTRAINT_PENDING -> INTENT_VALIDATED -> MERGE_ELIGIBLE`

A failed attestation yields `INTENT_RESTRAINT_FAILED`. Any remediation creates a new head and invalidates CI, technical review, and the prior intent/restraint attestation.

## Exact-state binding

The structured attestation is bound to `(head_sha, base_sha, wu_body_hash)` and includes independent reviewer identity plus head-bound material-author provenance. The controller must not derive this gate from free-form model prose.

A PASS requires all of the following to be explicitly true: frozen WU contract, intent preservation, scope discipline, minimal-change verification, no overengineering, existing-mechanism reuse or justification, convention preservation, architectural consistency, performance preservation, API/semantic preservation, proportional diff size, adversarial deletion review completion, and resolution of all deletion candidates.

The independent reviewer must explicitly answer the adversarial question: **What code in this PR is technically valid but should nevertheless be removed?**

## Stable failure codes

`INTENT_DRIFT`, `OVERENGINEERED`, `DUPLICATED_MECHANISM`, `PERFORMANCE_REGRESSION`, `SEMANTIC_CHANGE`, `DIFF_DISPROPORTIONATE`, `CONVENTION_DRIFT`, `ARCHITECTURE_DRIFT`, `UNRESOLVED_DELETION_CANDIDATES`, `SELF_REVIEW`, `ATTESTATION_INCOMPLETE`.

## Merge rule

`MERGE_OK_L5_1 := MERGE_OK_BASE AND INTENT_RESTRAINT_OK(exact head, exact base, frozen WU)`.

The pre-lock classifier may temporarily substitute the runtime-only merge-lock/fence fields solely to determine whether a PR is worth acquiring. Immediately before the write, the controller recomputes the complete predicate from a fresh snapshot and real lock/fence evidence.

## Certification

S1-S30 continue to certify coordination, recovery, security, and concurrency. S31-S40 add 10,000 hostile intent/restraint traces, producing a 40,000-trace minimum certification run before unattended activation.
''',
)

doc = read("docs/L5-STATE-MACHINE-V1.md")
if "L5-INTENT-RESTRAINT-V1.1.md" not in doc:
    doc += "\n\n## L5.1 Engineering Intent & Restraint\n\nThe merge contract is extended by `docs/L5-INTENT-RESTRAINT-V1.1.md`. Autonomous merge requires both the base `MERGE_OK` predicate and an exact-state independent intent/restraint PASS. Certification now includes S1-S40 for a minimum of 40,000 hostile traces.\n"
    write("docs/L5-STATE-MACHINE-V1.md", doc)

workflow = read(".github/workflows/l5-hostile-controller-ci.yml")
if "l5_intent_hostile_sim.py" not in workflow:
    workflow = workflow.replace(
        "      - scripts/l5_hostile_sim.py\n",
        "      - scripts/l5_hostile_sim.py\n      - scripts/l5_intent_hostile_sim.py\n",
        1,
    )
    workflow = workflow.replace(
        "      - tests/test_l5_controller.py\n",
        "      - tests/test_l5_controller.py\n      - tests/test_l5_intent_restraint.py\n",
        1,
    )
    workflow = workflow.replace(
        "      - docs/L5-STATE-MACHINE-V1.md\n",
        "      - docs/L5-STATE-MACHINE-V1.md\n      - docs/L5-INTENT-RESTRAINT-V1.1.md\n",
        1,
    )
    workflow += "      - name: S31-S40 intent and restraint hostile traces\n        run: python scripts/l5_intent_hostile_sim.py\n"
    write(".github/workflows/l5-hostile-controller-ci.yml", workflow)

print("L5 v1.1 one-shot patch applied")
