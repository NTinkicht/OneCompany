"""Regression tests for the provider-neutral, non-authoritative harness contract."""
from __future__ import annotations
import sys
import unittest
from dataclasses import replace
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from execution_core import RunKey
from harness_contract import COST_CLASSES, SEAMS, HarnessIntent, TrustedHarnessSnapshot, assess_intent
HEAD = "a" * 40
BASE = "b" * 40
KEY = RunKey("WU-P1-FOUNDATIONS-001", "run-one", 3)

def case():
    intent = HarnessIntent(key=KEY, project="example/private-project", actor="verified-bot", capability="implementation", head=HEAD, base=BASE, tools=frozenset({"read_file", "run_tests"}))
    trusted = TrustedHarnessSnapshot(key=KEY, project="example/private-project", head=HEAD, base=BASE, lease_actor="verified-bot", lease_capability="implementation", lease_active=True, permitted_tools=frozenset({"read_file", "run_tests"}), actor_verified=True, actor_cost_class="INCLUDED_SUBSCRIPTION", stop_active=False, extra_spend_cap=0)
    return intent, trusted

class HarnessContractTests(unittest.TestCase):
    def test_parent_matching_bounded_intent_can_be_considered_not_granted(self):
        intent, trusted = case(); verdict = assess_intent(intent, trusted)
        self.assertTrue(verdict.permitted); self.assertEqual(verdict.code, "ADMITTED_FOR_TRUSTED_PARENT"); self.assertIn("parent must still enforce", verdict.reason)

    def test_stale_run_generation_and_identity_refused(self):
        intent, trusted = case()
        for change, code in (({"key": RunKey(KEY.wu_id, KEY.run_id, 2)}, "STALE_GENERATION"), ({"key": RunKey("other", KEY.run_id, 3)}, "STALE_GENERATION"), ({"actor": "injected-bot"}, "WRONG_ACTOR"), ({"capability": "review"}, "CAPABILITY_NOT_LEASED"), ({"project": "other-project"}, "WRONG_PROJECT"), ({"head": BASE}, "NONDISTINCT_REVISIONS"), ({"head": "0" * 40}, "STALE_REVISION"), ({"base": "not-a-sha"}, "INVALID_REVISION")):
            with self.subTest(change=change): self.assertEqual(assess_intent(replace(intent, **change), trusted).code, code)

    def test_budget_and_entitlement_fail_closed(self):
        intent, trusted = case()
        for changes, code in (({"lease_active": False}, "LEASE_NOT_ACTIVE"), ({"stop_active": True}, "EMERGENCY_STOP"), ({"actor_verified": False}, "ACTOR_NOT_VERIFIED"), ({"actor_cost_class": "UNKNOWN_COST"}, "COST_CLASS_BLOCKED"), ({"actor_cost_class": "METERED_ALLOWED"}, "COST_CLASS_BLOCKED"), ({"extra_spend_cap": 1}, "EXTRA_SPEND_BLOCKED")):
            with self.subTest(changes=changes): self.assertEqual(assess_intent(intent, replace(trusted, **changes)).code, code)
        for spend in (-1, 1, True, 0.01): self.assertEqual(assess_intent(replace(intent, requested_extra_spend=spend), trusted).code, "EXTRA_SPEND_BLOCKED")

    def test_trusted_boolean_flags_require_exact_bool(self):
        intent, trusted = case()
        for field in ("stop_active", "lease_active", "actor_verified", "provider_available"):
            for value in (None, 0, 1, "", "false", [], object()):
                with self.subTest(field=field, value=repr(value)):
                    verdict = assess_intent(intent, replace(trusted, **{field: value}))
                    self.assertFalse(verdict.permitted)
                    self.assertEqual(verdict.code, "INVALID_TRUSTED_SNAPSHOT")

    def test_unknown_provider_and_optional_outage_never_expand_scope(self):
        intent, trusted = case()
        for seam in SEAMS:
            expected = assess_intent(replace(intent, provider_seam=seam), trusted, provider_configuration={"native": True})
            self.assertEqual(expected.permitted, seam == "native", f"{seam} unexpectedly enabled")
        self.assertEqual(assess_intent(replace(intent, provider_seam="kserve"), trusted).code, "UNKNOWN_PROVIDER_SEAM")
        self.assertEqual(assess_intent(intent, replace(trusted, provider_available=False)).code, "PROVIDER_UNAVAILABLE")
        self.assertEqual(assess_intent(replace(intent, provider_seam="memory"), trusted, provider_configuration={"native": True}).code, "PROVIDER_NOT_CONFIGURED")
        self.assertEqual(assess_intent(replace(intent, provider_seam="memory"), trusted).code, "PROVIDER_NOT_CONFIGURED")
        self.assertEqual(assess_intent(replace(intent, provider_seam="memory"), trusted, provider_configuration={"memory": 1}).code, "PROVIDER_NOT_CONFIGURED")
        self.assertTrue(assess_intent(replace(intent, provider_seam="memory"), trusted, provider_configuration={"memory": True}).permitted)

    def test_write_and_merge_cannot_be_self_granted(self):
        intent, trusted = case()
        for tools, expected in [(frozenset({"read_file", "write_file"}), "TOOL_SCOPE_BLOCKED"), (frozenset({"read_file", "merge_pr"}), "TOOL_SCOPE_BLOCKED"), (frozenset({"approve_pr"}), "TOOL_SCOPE_BLOCKED"), (frozenset(), "TOOL_SCOPE_BLOCKED")]: self.assertEqual(assess_intent(replace(intent, tools=tools), trusted).code, expected)
        elevated = replace(trusted, permitted_tools=frozenset({"read_file", "merge_pr"}))
        self.assertEqual(assess_intent(replace(intent, tools=frozenset({"merge_pr"})), elevated).code, "GOVERNANCE_TOOL_BLOCKED")

    def test_code_does_not_call_provider_or_mutate_onecompany_state(self):
        self.assertNotIn("METERED_ALLOWED", COST_CLASSES)
        intent, snapshot = case(); before = repr(snapshot); assess_intent(intent, snapshot); self.assertEqual(repr(snapshot), before)

if __name__ == "__main__": unittest.main()
