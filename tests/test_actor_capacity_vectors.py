"""OC-P0-08 vectors for actor_capacity_report: zero implicit PAYG and the outage matrix.

Positive control: mistral-vibe/code_review is ELIGIBLE on the committed
control plane. Every refusal test applies exactly one mutation to a deep copy
of that baseline and asserts the exact reason, so a refusal cannot pass by
being blocked for an unrelated cause.
"""
import contextlib
import copy
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import actor_capacity_report as report  # noqa: E402

ACTOR, CAP = "mistral-vibe", "code_review"
ELIGIBLE = "ELIGIBLE_FOR_FURTHER_LEASE_CHECKS"


def load(name):
    return json.loads((ROOT / ".onecompany" / name).read_text())


class ActorCapacityVectors(unittest.TestCase):
    def setUp(self):
        self.actors, self.ready = load("actors.json"), load("readiness.json")
        self.dispatch, self.budget = load("dispatch.json"), load("budget.json")

    def run_diag(self, **kw):
        return report.diagnose(
            kw.pop("actor", ACTOR), kw.pop("cap", CAP), self.actors, self.ready,
            self.dispatch, self.budget, **kw)

    def row(self, doc, key="actor_id"):
        return next(x for x in doc["actors"] if x[key] == ACTOR)

    def assertBlockedOnlyBy(self, result, reason):
        self.assertEqual(result["admission"], "NOT_QUALIFIED")
        self.assertEqual(result["reasons"], [reason])

    def test_positive_control_is_eligible_with_no_reasons(self):
        result = self.run_diag()
        self.assertEqual(result["admission"], ELIGIBLE)
        self.assertEqual(result["reasons"], [])
        self.assertEqual(result["financial_policy"], "ALLOWED_NO_ADDITIONAL_SPEND")

    def test_each_spend_flag_alone_blocks_financially(self):
        for key, value in (("allow_paid_fallback", True), ("allow_overage", True),
                           ("allow_auto_topup", True), ("allow_new_paid_vendor", True),
                           ("additional_monthly_spend_cap", 1),
                           ("unknown_cost_behavior", "allow_within_cap")):
            with self.subTest(key=key):
                self.budget["ai"][key] = value
                self.assertBlockedOnlyBy(self.run_diag(), "financial_policy_blocked")
                self.budget = load("budget.json")

    def test_missing_spend_flag_is_not_treated_as_false(self):
        for key in ("allow_paid_fallback", "allow_overage", "allow_auto_topup",
                    "allow_new_paid_vendor", "unknown_cost_behavior"):
            with self.subTest(key=key):
                del self.budget["ai"][key]
                self.assertBlockedOnlyBy(self.run_diag(), "financial_policy_blocked")
                self.budget = load("budget.json")

    def test_forbidden_cost_class_blocks(self):
        self.row(self.actors, "id")["cost_class"] = "PAYG_API"
        self.assertBlockedOnlyBy(self.run_diag(), "financial_policy_blocked")

    def test_unknown_cost_class_blocks_under_forbid(self):
        self.row(self.actors, "id").pop("cost_class")
        result = self.run_diag()
        self.assertEqual(result["cost_class"], "UNKNOWN_COST")
        self.assertBlockedOnlyBy(result, "financial_policy_blocked")

    def test_temporary_outage_blocks_capability(self):
        self.row(self.ready)["temporarily_unavailable_capabilities"] = [CAP]
        self.assertBlockedOnlyBy(self.run_diag(), "capability_temporarily_unavailable")

    def test_unverified_capability_blocks(self):
        self.row(self.ready)["verified_capabilities"].remove(CAP)
        self.assertBlockedOnlyBy(self.run_diag(), "capability_not_verified")

    def test_actor_not_ready_blocks(self):
        for state in ("not_started", "blocked", "unknown"):
            with self.subTest(state=state):
                self.row(self.ready)["setup_state"] = state
                self.assertBlockedOnlyBy(self.run_diag(), "actor_not_ready")

    def test_degraded_state_alone_does_not_block(self):
        self.row(self.ready)["setup_state"] = "degraded"
        self.assertEqual(self.run_diag()["admission"], ELIGIBLE)

    def test_unattended_requires_both_configured_and_verified(self):
        for field in ("configured", "verified"):
            with self.subTest(field=field):
                self.row(self.ready)["unattended"][field] = False
                self.assertBlockedOnlyBy(self.run_diag(), "unattended_not_verified")
                self.ready = load("readiness.json")

    def test_interactive_mode_skips_unattended_requirement_only(self):
        self.row(self.ready)["unattended"] = {"configured": False, "verified": False}
        self.assertEqual(self.run_diag(unattended=False)["admission"], ELIGIBLE)
        self.assertBlockedOnlyBy(self.run_diag(unattended=True), "unattended_not_verified")

    def test_review_access_missing_blocks(self):
        self.row(self.ready)["repository_access"]["review"] = False
        self.assertBlockedOnlyBy(self.run_diag(), "repository_review_not_verified")

    def test_unconfigured_mechanism_blocks(self):
        for m in self.row(self.dispatch)["mechanisms"]:
            if m["id"] == "vibe-exact-head-review":
                m["configured"] = False
        self.assertBlockedOnlyBy(self.run_diag(), "no_configured_execution_mechanism")

    def test_attended_only_mechanism_blocked_when_unattended(self):
        for m in self.row(self.dispatch)["mechanisms"]:
            if m["id"] == "vibe-exact-head-review":
                m["unattended"] = False
        self.assertBlockedOnlyBy(self.run_diag(), "no_configured_execution_mechanism")
        self.assertEqual(self.run_diag(unattended=False)["admission"], ELIGIBLE)

    def test_disabled_or_unconfigured_actor_blocks(self):
        for field in ("enabled", "configured"):
            with self.subTest(field=field):
                self.row(self.actors, "id")[field] = False
                self.assertBlockedOnlyBy(self.run_diag(), "actor_not_enabled_and_configured")
                self.actors = load("actors.json")

    def test_missing_readiness_row_blocks(self):
        self.ready["actors"] = [x for x in self.ready["actors"] if x["actor_id"] != ACTOR]
        self.assertBlockedOnlyBy(self.run_diag(), "missing_readiness")

    def test_duplicate_registry_entries_raise_in_every_document(self):
        for doc, key in (("actors", "id"), ("ready", "actor_id"), ("dispatch", "actor_id")):
            with self.subTest(doc=doc):
                target = getattr(self, doc)
                target["actors"].append(copy.deepcopy(self.row(target, key)))
                with self.assertRaisesRegex(ValueError, "DUPLICATE_ACTOR_REGISTRY_ENTRY"):
                    self.run_diag()
                setattr(self, doc, load({"actors": "actors.json", "ready": "readiness.json",
                                         "dispatch": "dispatch.json"}[doc]))

    def test_every_failure_status_maps_to_a_distinct_nonfinancial_or_named_kind(self):
        self.assertEqual(report.FAILURE_KIND["WAKE_TIMEOUT"], "MODEL_EXECUTION_TIMEOUT")
        for status, kind in report.FAILURE_KIND.items():
            with self.subTest(status=status):
                result = self.run_diag(runtime_status=status)
                self.assertEqual(result["observed_runtime_failure"], kind)
                # an observed runtime failure never grants or revokes eligibility itself
                self.assertEqual(result["admission"], ELIGIBLE)

    def test_main_exit_codes_and_unavailable_on_bad_input(self):
        docs = {"actors.json": self.actors, "readiness.json": self.ready,
                "dispatch.json": self.dispatch, "budget.json": self.budget}

        def run_main(loader, argv):
            out = io.StringIO()
            with mock.patch.object(report, "load_json", loader), \
                 mock.patch.object(sys, "argv", ["x", *argv]), \
                 contextlib.redirect_stdout(out):
                code = report.main()
            return code, json.loads(out.getvalue())

        code, out = run_main(lambda p: docs[Path(p).name], ["--actor", ACTOR, "--capability", CAP])
        self.assertEqual((code, out["admission"]), (0, ELIGIBLE))
        code, out = run_main(lambda p: docs[Path(p).name], ["--actor", "nobody", "--capability", CAP])
        self.assertEqual(code, 2)
        self.assertIn("unknown_actor", out["reasons"])

        def broken(p):
            raise OSError("unreadable")
        code, out = run_main(broken, ["--actor", ACTOR, "--capability", CAP])
        self.assertEqual((code, out), (2, {"status": "CAPACITY_DIAGNOSTIC_UNAVAILABLE"}))


if __name__ == "__main__":
    unittest.main()
