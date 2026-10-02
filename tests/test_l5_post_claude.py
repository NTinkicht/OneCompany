from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from l5_api_hostile_sim import run_simulation as run_api_hostile_sim
from l5_liveness import check_liveness
from l5_shadow import shadow_evaluate
from l5_trust_boundary import load_trust_policy, review_is_independent


class TrustBoundaryTests(unittest.TestCase):
    def test_policy_loads_and_has_binding_reviewer(self):
        policy = load_trust_policy(ROOT / ".l5" / "trust-policy.json")
        self.assertTrue(policy.binding_reviewer_logins)
        self.assertIn("coderabbitai", policy.binding_reviewer_logins)
        self.assertEqual(len(policy.policy_hash), 64)

    def test_exact_head_independent_review_passes(self):
        policy = load_trust_policy(ROOT / ".l5" / "trust-policy.json")
        h, b = "a" * 40, "b" * 40
        review = {
            "state": "APPROVED", "commit_id": h, "base_sha": b,
            "complete": True, "skipped": False, "covers_full_diff": True,
            "identity_source_verified": True, "author": "coderabbitai",
        }
        ok, reasons = review_is_independent(
            review, policy=policy, head_sha=h, base_sha=b,
            material_authors=["chatgpt"],
        )
        self.assertTrue(ok, reasons)

    def test_stale_or_material_author_review_fails(self):
        policy = load_trust_policy(ROOT / ".l5" / "trust-policy.json")
        h, b = "a" * 40, "b" * 40
        stale = {
            "state":"APPROVED","commit_id":"c"*40,"base_sha":b,"complete":True,
            "skipped":False,"covers_full_diff":True,"identity_source_verified":True,
            "author":"coderabbitai",
        }
        self.assertFalse(review_is_independent(
            stale, policy=policy, head_sha=h, base_sha=b,
            material_authors=["chatgpt"],
        )[0])
        self_author = dict(stale, commit_id=h, author="chatgpt")
        self.assertFalse(review_is_independent(
            self_author, policy=policy, head_sha=h, base_sha=b,
            material_authors=["chatgpt"],
        )[0])


class ShadowTests(unittest.TestCase):
    def test_shadow_never_writes(self):
        repo_snapshot = {
            "platform_enforcement_ok": False,
            "live_rules_at_least_pinned": False,
            "rulesets_or_protection_active": False,
            "required_check_sources_pinned": False,
        }
        item_snapshot = {
            "repo":"NTinkicht/OneCompany","head_sha":"a"*40,"base_sha":"b"*40,
            "ci":"SUCCESS","review":"PASS","mergeable":True,
        }
        result = shadow_evaluate(repo_snapshot, item_snapshot)
        self.assertEqual(result["writes"], 0)
        self.assertFalse(result["mutation_allowed"])


class ApiHostileSimulationTests(unittest.TestCase):
    def test_randomized_api_faults_preserve_invariants(self):
        summary = run_api_hostile_sim(rounds=25, seed=123)
        self.assertEqual(summary["rounds"], 25)
        self.assertEqual(summary["scenarios"], 12)
        self.assertEqual(summary["traces"], 25 * 12)
        self.assertEqual(summary["seed"], 123)


class LivenessTests(unittest.TestCase):
    def test_good_trace_passes(self):
        zero_budget = {"ci_reruns":0,"fix_iterations":0,"review_rounds":0,"lease_acquisitions":0}
        events = [
            {"repo":"r","item_id":"1","status":"WAIT","state":"WAIT_CI","reason":"WAIT_CI","writes":0,"budget":dict(zero_budget)},
            {"repo":"r","item_id":"1","status":"COMPLETE","state":"MERGED_VERIFIED","reason":"POST_MERGE_VERIFIED","writes":1,"budget":{"ci_reruns":0,"fix_iterations":1,"review_rounds":1,"lease_acquisitions":2}},
            {"repo":"r","item_id":"repo","status":"IDLE","state":"IDLE","reason":"NO_ACTIONABLE_ITEM","writes":0,"external_changes":False,"stable_cycle":True,"budget":dict(zero_budget)},
        ]
        self.assertTrue(check_liveness(events)[0])

    def test_budget_and_idle_violations_fail(self):
        events = [
            {"repo":"r","item_id":"1","status":"WAIT","state":"X","reason":"X","writes":1,"external_changes":False,"stable_cycle":True,"budget":{"ci_reruns":3}}
        ]
        ok, failures = check_liveness(events)
        self.assertFalse(ok)
        self.assertIn("BUDGET_INVALID_CI_RERUNS", failures)
        self.assertIn("IDLE_NOT_QUIESCENT", failures)

    def test_changing_reason_does_not_mask_stagnation(self):
        budget = {"ci_reruns":0,"fix_iterations":0,"review_rounds":0,"lease_acquisitions":0}
        events = [
            {"repo":"r","item_id":"1","status":"BLOCKED","state":"SAME","head":"a"*40,"base":"b"*40,"reason":f"diagnostic-{i}","writes":0,"budget":budget}
            for i in range(7)
        ]
        ok, failures = check_liveness(events, max_stagnant_runs=5)
        self.assertFalse(ok)
        self.assertIn("UNBOUNDED_STAGNATION", failures)

    def test_malformed_status_fails_closed(self):
        budget = {"ci_reruns":0,"fix_iterations":0,"review_rounds":0,"lease_acquisitions":0}
        ok, failures = check_liveness([
            {"repo":"r","item_id":"1","status":["WAIT"],"state":"X","reason":"WAIT_CI","writes":0,"budget":budget}
        ])
        self.assertFalse(ok)
        self.assertIn("RUN_NOT_TERMINAL", failures)


if __name__ == "__main__":
    unittest.main()
