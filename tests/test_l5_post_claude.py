#!/usr/bin/env python3
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from l5_kernel import Budget
from l5_api_hostile_sim import run as run_api_hostile_sim
from l5_liveness import check_liveness
from l5_shadow import shadow_evaluate
from l5_trust_boundary import (
    TrustPolicy,
    credential_boundary_ok,
    review_is_independent,
    trust_boundary_ok,
)

H = "a" * 40
B = "b" * 40


def load_policy():
    return TrustPolicy.from_mapping(json.loads((ROOT / ".l5" / "trust-policy.json").read_text()))


def review(author="coderabbitai"):
    return {
        "state": "APPROVED",
        "commit_id": H,
        "base_sha": B,
        "complete": True,
        "skipped": False,
        "covers_full_diff": True,
        "identity_source_verified": True,
        "author": author,
    }


def credential_evidence(**overrides):
    out = {
        "controller_executes_repository_code": False,
        "test_worker_has_write_token": False,
        "write_token_in_test_env": False,
        "actuator_executes_repository_code": False,
        "repo_code_runs_in_actuator": False,
        "actuator_accepts_structured_only": True,
        "credential_boundary_verified": True,
    }
    out.update(overrides)
    return out


def shadow_repo(**overrides):
    out = {
        "halted": False,
        "controller_integrity_failure": False,
        "security_integrity_failure": False,
        "ledger_reachable": True,
        "platform_enforcement_ok": False,
        "live_rules_at_least_pinned": False,
        "rulesets_or_protection_active": False,
        "required_check_sources_pinned": False,
        "controller_admin": False,
        "controller_bypass": False,
        "merge_locked": False,
        "archived_or_permission_lost": False,
    }
    out.update(overrides)
    return out


class TrustBoundaryTests(unittest.TestCase):
    def test_pinned_external_reviewer_passes(self):
        ok, failures = review_is_independent(
            review(), policy=load_policy(), head_sha=H, base_sha=B, material_authors=["chatgpt"]
        )
        self.assertTrue(ok, failures)

    def test_controller_or_unregistered_reviewer_never_passes(self):
        policy = load_policy()
        for actor in ("ntinkicht", "chatgpt", "random-review-bot"):
            ok, failures = review_is_independent(
                review(actor), policy=policy, head_sha=H, base_sha=B, material_authors=["chatgpt"]
            )
            self.assertFalse(ok)
            self.assertTrue(failures)

    def test_exact_head_and_base_are_valid_shas_and_must_match(self):
        policy = load_policy()
        self.assertFalse(review_is_independent(review(), policy=policy, head_sha="", base_sha=B, material_authors=[])[0])
        self.assertFalse(review_is_independent(review(), policy=policy, head_sha=H, base_sha="not-a-sha", material_authors=[])[0])
        bad = review(); bad["commit_id"] = "c" * 40
        self.assertFalse(review_is_independent(bad, policy=policy, head_sha=H, base_sha=B, material_authors=[])[0])
        bad = review(); bad["base_sha"] = "d" * 40
        self.assertFalse(review_is_independent(bad, policy=policy, head_sha=H, base_sha=B, material_authors=[])[0])

    def test_credential_isolation_fails_closed(self):
        self.assertTrue(credential_boundary_ok(credential_evidence())[0])
        for key in (
            "controller_executes_repository_code",
            "test_worker_has_write_token",
            "write_token_in_test_env",
            "actuator_executes_repository_code",
            "repo_code_runs_in_actuator",
        ):
            self.assertFalse(credential_boundary_ok(credential_evidence(**{key: True}))[0], key)
        self.assertFalse(credential_boundary_ok(credential_evidence(actuator_accepts_structured_only=False))[0])
        self.assertFalse(credential_boundary_ok({})[0])

    def test_combined_trust_boundary_binds_policy_hash(self):
        policy = load_policy()
        evidence = {
            "review": review(),
            "credential_boundary": credential_evidence(),
            "trust_policy_hash": policy.policy_hash,
        }
        self.assertTrue(trust_boundary_ok(evidence, policy=policy, head_sha=H, base_sha=B, material_authors=["chatgpt"])[0])
        evidence["trust_policy_hash"] = "0" * 64
        self.assertFalse(trust_boundary_ok(evidence, policy=policy, head_sha=H, base_sha=B, material_authors=["chatgpt"])[0])


class ShadowModeTests(unittest.TestCase):
    def test_shadow_is_read_only_and_platform_gate_is_deferred(self):
        result = shadow_evaluate(shadow_repo(), {"no_actionable_work": True}, budget=Budget())
        self.assertEqual(result["mode"], "SHADOW")
        self.assertFalse(result["mutation_allowed"])
        self.assertEqual(result["writes"], 0)
        self.assertIn("PLATFORM_ENFORCEMENT_DEFERRED", result["activation_blockers"])
        self.assertNotIn("STAGED_REPO_MODE_GOVERNANCE_DRIFT", result["activation_blockers"])

    def test_nonplatform_governance_failure_is_not_staged_away(self):
        result = shadow_evaluate(
            shadow_repo(controller_integrity_failure=True),
            {"no_actionable_work": True},
            budget=Budget(),
        )
        self.assertIn("STAGED_REPO_MODE_CONTROLLER_INTEGRITY", result["activation_blockers"])
        self.assertFalse(result["mutation_allowed"])


class ApiSimulatorTests(unittest.TestCase):
    def test_randomized_api_faults_preserve_invariants(self):
        counts = run_api_hostile_sim(rounds=25, seed=123)
        self.assertEqual(set(counts), {f"A{i}" for i in range(1, 13)})
        self.assertTrue(all(value == 25 for value in counts.values()))


class LivenessTests(unittest.TestCase):
    def test_good_trace_passes(self):
        events = [
            {"repo":"r","item_id":"1","status":"WAIT","state":"WAIT_CI","reason":"WAIT_CI","writes":0,"budget":{}},
            {"repo":"r","item_id":"1","status":"COMPLETE","state":"MERGED_VERIFIED","reason":"POST_MERGE_VERIFIED","writes":1,"budget":{"ci_reruns":0,"fix_iterations":1,"review_rounds":1,"lease_acquisitions":2}},
            {"repo":"r","item_id":"repo","status":"IDLE","state":"IDLE","reason":"NO_ACTIONABLE_ITEM","writes":0,"external_changes":False,"stable_cycle":True,"budget":{}},
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

    def test_malformed_or_negative_budget_fails_closed(self):
        for budget in (None, [], {"ci_reruns": -1}, {"review_rounds": "1"}):
            ok, failures = check_liveness([
                {"repo":"r","item_id":"1","status":"IDLE","state":"IDLE","reason":"NO_ACTIONABLE_ITEM","writes":0,"budget":budget}
            ])
            self.assertFalse(ok, budget)
            self.assertTrue(any(code.startswith("BUDGET_") for code in failures), (budget, failures))


if __name__ == "__main__":
    unittest.main()
