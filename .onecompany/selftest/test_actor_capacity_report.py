"""Source-only tests: a subscription is not equivalent to a leased model worker."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import actor_capacity_report as report


class ActorCapacityReportTests(unittest.TestCase):
    """Verify truthful separation of model quota, policy and actor readiness."""

    @classmethod
    def setUpClass(cls):
        cls.actors = json.loads((ROOT / ".onecompany/actors.json").read_text())
        cls.ready = json.loads((ROOT / ".onecompany/readiness.json").read_text())
        cls.dispatch = json.loads((ROOT / ".onecompany/dispatch.json").read_text())
        cls.budget = json.loads((ROOT / ".onecompany/budget.json").read_text())

    def check(self, actor, capability="implementation", **extra):
        return report.diagnose(
            actor, capability, self.actors, self.ready, self.dispatch,
            self.budget, **extra
        )

    def test_mistral_included_plan_is_not_qualified_writer(self):
        actual = self.check("mistral-vibe")
        self.assertEqual(actual["cost_class"], "INCLUDED_SUBSCRIPTION")
        self.assertEqual(actual["financial_policy"], "ALLOWED_NO_ADDITIONAL_SPEND")
        self.assertEqual(actual["provider_quota"], "NOT_PROBED_BY_LEASE")
        self.assertEqual(actual["model_token_ceiling"], "NOT_PROBED_BY_LEASE")
        self.assertEqual(actual["admission"], "NOT_QUALIFIED")
        self.assertEqual(actual["implementation_free_slots"], 0)
        self.assertIn("implementation_not_verified", actual["reasons"])
        self.assertIn("repository_write_not_verified", actual["reasons"])
        self.assertIn("no_configured_execution_mechanism", actual["reasons"])
        self.assertNotIn("financial_policy_blocked", actual["reasons"])

    def test_grok_included_plan_does_not_imply_cloud_writer_or_reviewer(self):
        for capability in ("implementation", "code_review"):
            with self.subTest(capability=capability):
                actual = self.check("grok-4-6-interactive", capability)
                self.assertEqual(actual["financial_policy"],
                                 "ALLOWED_NO_ADDITIONAL_SPEND")
                self.assertEqual(actual["admission"], "NOT_QUALIFIED")
                self.assertEqual(actual["configured_mechanisms"], [])
                self.assertIn("capability_not_verified", actual["reasons"])
                self.assertNotIn("financial_policy_blocked", actual["reasons"])

    def test_token_ceiling_is_not_provider_quota_or_financial_budget(self):
        labels = {
            "TOKEN_BUDGET_EXCEEDED": "MODEL_EXECUTION_TOKEN_CEILING",
            "TURN_LIMIT_EXCEEDED": "MODEL_EXECUTION_TURN_CEILING",
            "CAPACITY_DEGRADED": "PROVIDER_QUOTA_OR_RATE_LIMIT_UNVERIFIED",
            "PROVIDER_QUOTA_EXHAUSTED": "PROVIDER_QUOTA_OR_RATE_LIMIT",
            "BUDGET_BLOCKED": "FINANCIAL_POLICY_BLOCKED",
            "AUTH_BLOCKED": "PROVIDER_AUTHENTICATION_BLOCKED",
        }
        for status, kind in labels.items():
            with self.subTest(status=status):
                actual = self.check("mistral-vibe", runtime_status=status)
                self.assertEqual(actual["observed_runtime_failure"], kind)
                self.assertEqual(actual["provider_quota"], "NOT_PROBED_BY_LEASE")
        self.assertEqual(report.classify_failure(None), "NOT_PROBED")
        self.assertEqual(report.classify_failure("SOME_UNRECOGNIZED_ERROR"),
                         "UNCLASSIFIED_RUNTIME_STATUS")

    def test_financial_policy_is_independent_and_fail_closed(self):
        for key, value in (
            ("allow_paid_fallback", True),
            ("allow_overage", True),
            ("additional_monthly_spend_cap", 1),
            ("unknown_cost_behavior", "allow"),
        ):
            budget = copy.deepcopy(self.budget)
            budget["ai"][key] = value
            with self.subTest(key=key):
                actual = report.diagnose(
                    "mistral-vibe", "implementation", self.actors,
                    self.ready, self.dispatch, budget
                )
                self.assertEqual(actual["financial_policy"],
                                 "FINANCIAL_POLICY_BLOCKED")
                self.assertIn("financial_policy_blocked", actual["reasons"])

    def test_verified_capability_without_execution_mechanism_stays_blocked(self):
        ready = copy.deepcopy(self.ready)
        row = next(x for x in ready["actors"] if x["actor_id"] == "mistral-vibe")
        row["verified_capabilities"].append("implementation")
        row["repository_access"]["write"] = True
        row["capacity"]["implementation_streams"] = 1
        actual = report.diagnose(
            "mistral-vibe", "implementation", self.actors,
            ready, self.dispatch, self.budget,
        )
        self.assertEqual(actual["admission"], "NOT_QUALIFIED")
        self.assertIn("unattended_implementation_dispatch_missing",
                      actual["reasons"])
        self.assertIn("no_configured_execution_mechanism", actual["reasons"])

    def test_unknown_actor_never_inherits_another_plan(self):
        actual = self.check("mistral-vibe-other")
        self.assertEqual(actual["financial_policy"], "FINANCIAL_POLICY_BLOCKED")
        self.assertIn("unknown_actor", actual["reasons"])
        self.assertEqual(actual["admission"], "NOT_QUALIFIED")


if __name__ == "__main__":
    unittest.main()
