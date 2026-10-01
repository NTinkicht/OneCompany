#!/usr/bin/env python3
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
