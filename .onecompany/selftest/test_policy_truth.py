from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import policy_truth


class PolicyTruthTests(unittest.TestCase):
    def test_every_current_machine_policy_key_gets_a_truth_class_and_owner(self):
        inventory = policy_truth.generate_inventory()
        self.assertTrue(inventory)
        for entry in inventory:
            self.assertIn(entry["classification"], {"ENFORCED", "GUIDANCE", "REMOVED"})
            self.assertTrue(entry["owner"])
            self.assertTrue(entry["file"])
            self.assertTrue(entry["path"].startswith("/"))

    def test_unconsumed_key_cannot_be_falsely_claimed_enforced(self):
        inventory = [
            {
                "file": "config.json",
                "path": "/decorative_future_switch",
                "key": "decorative_future_switch",
                "classification": "GUIDANCE",
                "owner": "guidance-only",
                "evidence": [],
            }
        ]
        claims = [
            {
                "file": "config.json",
                "path": "/decorative_future_switch",
                "classification": "ENFORCED",
                "tests": [".onecompany/selftest/test_policy_truth.py"],
            }
        ]
        errors = policy_truth.validate_claims(inventory, claims, root=ROOT)
        self.assertTrue(any("unsupported ENFORCED claim" in error for error in errors), errors)

    def test_enforced_claim_requires_executable_test_evidence(self):
        inventory = [
            {
                "file": "budget.json",
                "path": "/ai/additional_monthly_spend_cap",
                "key": "additional_monthly_spend_cap",
                "classification": "ENFORCED",
                "owner": "validate.py",
                "evidence": ["validate.py"],
            }
        ]
        claims = [
            {
                "file": "budget.json",
                "path": "/ai/additional_monthly_spend_cap",
                "classification": "ENFORCED",
                "tests": [],
            }
        ]
        errors = policy_truth.validate_claims(inventory, claims, root=ROOT)
        self.assertTrue(any("requires at least one executable test" in error for error in errors), errors)

    def test_guidance_claim_cannot_hide_an_authority_consumer(self):
        inventory = [
            {
                "file": "planning.json",
                "path": "/parallel_execution/max_concurrent_implementation_streams",
                "key": "max_concurrent_implementation_streams",
                "classification": "ENFORCED",
                "owner": "planning_lib.py",
                "evidence": ["planning_lib.py"],
            }
        ]
        claims = [
            {
                "file": "planning.json",
                "path": "/parallel_execution/max_concurrent_implementation_streams",
                "classification": "GUIDANCE",
            }
        ]
        errors = policy_truth.validate_claims(inventory, claims, root=ROOT)
        self.assertTrue(any("must not be presented as guidance" in error for error in errors), errors)

    def test_array_records_generate_one_normalized_inventory_path(self):
        entries = policy_truth.enumerate_keys(
            {"actors": [{"enabled": True}, {"enabled": False}]}
        )
        self.assertEqual(entries.count(("/actors/*/enabled", "enabled")), 1)

    def test_deleting_enforced_claim_fails_monotonic_history(self):
        base_claims = [
            {
                "file": "budget.json",
                "path": "/ai/additional_monthly_spend_cap",
                "classification": "ENFORCED",
            }
        ]
        errors = policy_truth.validate_claim_history(base_claims, [])
        self.assertTrue(any("silently removes existing policy claim" in error for error in errors), errors)

    def test_deleting_guidance_claim_requires_explicit_removal(self):
        base_claims = [
            {
                "file": "config.json",
                "path": "/future_switch",
                "classification": "GUIDANCE",
            }
        ]
        errors = policy_truth.validate_claim_history(base_claims, [])
        self.assertTrue(any("retain it as REMOVED" in error for error in errors), errors)

    def test_explicit_reviewable_removal_can_pass_when_key_and_consumer_are_gone(self):
        base_claims = [
            {
                "file": "config.json",
                "path": "/retired_switch",
                "classification": "ENFORCED",
            }
        ]
        current_claims = [
            {
                "file": "config.json",
                "path": "/retired_switch",
                "classification": "REMOVED",
                "removal_rationale": "The retired feature and its enforcement path were deleted.",
                "removal_provenance": "PR #999 approved deprecation",
            }
        ]
        self.assertEqual(policy_truth.validate_claim_history(base_claims, current_claims), [])
        self.assertEqual(
            policy_truth.validate_claims(
                [],
                current_claims,
                root=ROOT,
                source_index={"retired_switch": set()},
            ),
            [],
        )

    def test_removed_claim_cannot_hide_a_remaining_enforcement_consumer(self):
        claims = [
            {
                "file": "config.json",
                "path": "/retired_switch",
                "classification": "REMOVED",
                "removal_rationale": "Feature retired.",
                "removal_provenance": "PR #999",
            }
        ]
        errors = policy_truth.validate_claims(
            [],
            claims,
            root=ROOT,
            source_index={"retired_switch": {"validate.py"}},
        )
        self.assertTrue(any("still consumed by enforcing module" in error for error in errors), errors)

    def test_removed_claim_cannot_be_resurrected(self):
        base_claims = [
            {
                "file": "config.json",
                "path": "/retired_switch",
                "classification": "REMOVED",
                "removal_rationale": "Retired.",
                "removal_provenance": "PR #999",
            }
        ]
        current_claims = [
            {
                "file": "config.json",
                "path": "/retired_switch",
                "classification": "GUIDANCE",
            }
        ]
        errors = policy_truth.validate_claim_history(base_claims, current_claims)
        self.assertTrue(any("resurrects previously REMOVED" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
