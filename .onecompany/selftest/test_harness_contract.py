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

    def test_run_key_requires_canonical_type_and_exact_integer_generation(self):
        intent, trusted = case()
        for generation in (True, False, 1.0, 3.0):
            malformed = RunKey(KEY.wu_id, KEY.run_id, generation)
            with self.subTest(side="intent", generation=repr(generation)): self.assertEqual(assess_intent(replace(intent, key=malformed), trusted).code, "INVALID_RUN_KEY")
            with self.subTest(side="snapshot", generation=repr(generation)): self.assertEqual(assess_intent(intent, replace(trusted, key=malformed)).code, "INVALID_RUN_KEY")
        for malformed in (None, object(), (KEY.wu_id, KEY.run_id, 3), {"generation": 3}):
            with self.subTest(side="intent", key=repr(malformed)): self.assertEqual(assess_intent(replace(intent, key=malformed), trusted).code, "INVALID_RUN_KEY")
            with self.subTest(side="snapshot", key=repr(malformed)): self.assertEqual(assess_intent(intent, replace(trusted, key=malformed)).code, "INVALID_RUN_KEY")

    def test_non_string_untrusted_revisions_are_refused_not_exceptions(self):
        intent, trusted = case()
        for field in ("head", "base"):
            for malformed in (None, 0, 1, True, False, b"a" * 40, [], {}, object()):
                with self.subTest(field=field, value=repr(malformed)):
                    result = assess_intent(replace(intent, **{field: malformed}), trusted)
                    self.assertFalse(result.permitted); self.assertEqual(result.code, "INVALID_REVISION")

    def test_budget_and_entitlement_fail_closed(self):
        intent, trusted = case()
        for changes, code in (({"lease_active": False}, "LEASE_NOT_ACTIVE"), ({"stop_active": True}, "EMERGENCY_STOP"), ({"actor_verified": False}, "ACTOR_NOT_VERIFIED"), ({"actor_cost_class": "UNKNOWN_COST"}, "COST_CLASS_BLOCKED"), ({"actor_cost_class": "METERED_ALLOWED"}, "COST_CLASS_BLOCKED"), ({"extra_spend_cap": 1}, "EXTRA_SPEND_BLOCKED")):
            with self.subTest(changes=changes): self.assertEqual(assess_intent(intent, replace(trusted, **changes)).code, code)
        for spend in (-1, 1, True, 0.01): self.assertEqual(assess_intent(replace(intent, requested_extra_spend=spend), trusted).code, "EXTRA_SPEND_BLOCKED")

    def test_resource_ceilings_are_exact_typed_bounded_and_parent_matched(self):
        intent, trusted = case()
        fields = ("max_tokens", "max_seconds", "max_output_bytes", "max_errors", "stall_seconds")
        for field in fields:
            for malformed in (True, 1.0, "1", None):
                with self.subTest(field=field, malformed=repr(malformed), side="intent"):
                    self.assertEqual(assess_intent(replace(intent, **{field: malformed}), trusted).code, "INVALID_RESOURCE_CEILINGS")
                with self.subTest(field=field, malformed=repr(malformed), side="snapshot"):
                    self.assertEqual(assess_intent(intent, replace(trusted, **{field: malformed})).code, "INVALID_RESOURCE_CEILINGS")
        for field in ("max_tokens", "max_seconds", "max_output_bytes", "stall_seconds"):
            self.assertEqual(assess_intent(replace(intent, **{field: 0}), replace(trusted, **{field: 0})).code, "INVALID_RESOURCE_CEILINGS")
        self.assertEqual(assess_intent(replace(intent, max_errors=-1), replace(trusted, max_errors=-1)).code, "INVALID_RESOURCE_CEILINGS")
        for field in fields:
            with self.subTest(field=field, mismatch=True):
                self.assertEqual(assess_intent(replace(intent, **{field: getattr(intent, field) + 1}), trusted).code, "RESOURCE_CEILINGS_MISMATCH")

    def test_malformed_actor_tools_and_provider_are_refused(self):
        intent, trusted = case()
        for field, denied in (("project", "WRONG_PROJECT"), ("actor", "WRONG_ACTOR"), ("capability", "CAPABILITY_NOT_LEASED"), ("provider_seam", "UNKNOWN_PROVIDER_SEAM")):
            for malformed in ([], {}, 1, None, True):
                with self.subTest(field=field, malformed=repr(malformed)):
                    result = assess_intent(replace(intent, **{field: malformed}), trusted)
                    self.assertFalse(result.permitted); self.assertEqual(result.code, denied)
        for malformed in ([], {}, 1, None): self.assertEqual(assess_intent(intent, replace(trusted, actor_cost_class=malformed)).code, "COST_CLASS_BLOCKED")
        for tools in (frozenset({1}), frozenset({None}), frozenset({""}), frozenset({"read_file", 1})):
            with self.subTest(tools=repr(tools)): self.assertEqual(assess_intent(replace(intent, tools=tools), replace(trusted, permitted_tools=tools)).code, "TOOL_SCOPE_BLOCKED")

    def test_trusted_boolean_flags_require_exact_bool(self):
        intent, trusted = case()
        for field in ("stop_active", "lease_active", "actor_verified", "provider_available"):
            for value in (None, 0, 1, "", "false", [], object()):
                with self.subTest(field=field, value=repr(value)):
                    verdict = assess_intent(intent, replace(trusted, **{field: value}))
                    self.assertFalse(verdict.permitted); self.assertEqual(verdict.code, "INVALID_TRUSTED_SNAPSHOT")

    def test_malformed_provider_configuration_fails_closed(self):
        intent, trusted = case()
        for malformed in ([], (), "native", 1, True, False, object()):
            with self.subTest(value=repr(malformed)):
                verdict = assess_intent(intent, trusted, provider_configuration=malformed)
                self.assertFalse(verdict.permitted); self.assertEqual(verdict.code, "INVALID_PROVIDER_CONFIGURATION")

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
