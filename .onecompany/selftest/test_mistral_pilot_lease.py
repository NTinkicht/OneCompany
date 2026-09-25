"""A single unqualified cloud agent cannot turn a pilot into generic authority."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from capacity_lib import implementation_availability
from ledger_lib import mistral_qualification_pilot_admission

REPO = "NTinkicht/OneCompany"
WU = "WU-CLOUD-MISTRAL-DEV-001"
PR = 224


class MistralQualificationPilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.actors = json.loads((ROOT / ".onecompany/actors.json").read_text())
        cls.readiness = json.loads((ROOT / ".onecompany/readiness.json").read_text())
        cls.queue = json.loads((ROOT / ".onecompany/queue.json").read_text())
        cls.budget = json.loads((ROOT / ".onecompany/budget.json").read_text())
        cls.config = json.loads((ROOT / ".onecompany/config.json").read_text())

    def policy(self):
        actor = next(x for x in self.actors["actors"] if x["id"] == "mistral-vibe")
        ready = next(x for x in self.readiness["actors"]
                     if x["actor_id"] == "mistral-vibe")
        item = next(x for x in self.queue["work_units"] if x["id"] == WU)
        # An unmerged queue binding is deliberately NOT admission authority.
        # Model the eventual reviewed protected-main queue value in this
        # pure offline test; the runtime uses only the verified PR base.
        item = copy.deepcopy(item)
        item["pr"] = PR
        return dict(repo=REPO, actor="mistral-vibe", pr=PR, work_unit=WU,
                    item=item, actor_record=copy.deepcopy(actor),
                    ready=copy.deepcopy(ready), budget=copy.deepcopy(self.budget),
                    config=copy.deepcopy(self.config))

    def test_one_exact_bound_candidate_is_admissible_as_a_pilot(self):
        p = self.policy()
        self.assertTrue(mistral_qualification_pilot_admission(**p))
        slots, reasons = implementation_availability(
            p["actor_record"], p["ready"], p["budget"], [])
        self.assertEqual(slots, 0)
        self.assertIn("implementation_not_verified", reasons)
        self.assertIn("repository_write_not_verified", reasons)

    def test_other_actor_repository_work_unit_or_pr_is_never_admitted(self):
        for key, value in (
            ("repo", "example/customer"),
            ("actor", "grok-4-6-interactive"),
            ("work_unit", "WU-UNRELATED"),
            ("pr", 225),
            ("pr", None),
            ("item", None),
        ):
            p = self.policy()
            p[key] = value
            with self.subTest(key=key, value=value):
                self.assertFalse(mistral_qualification_pilot_admission(**p))

    def test_exact_scope_branch_status_risk_and_binding_immutable(self):
        for key, value in (
            ("id", "WU-OTHER"),
            ("pr", 223),
            ("issue", 132),
            ("status", "DONE"),
            ("risk_class", "HIGH"),
            ("branch", "main"),
            ("dependencies", []),
            ("write_scope", ["**/*"]),
            ("write_scope", ["tests/test_agent_qualification.py"]),
            ("resource_locks", []),
        ):
            p = self.policy()
            p["item"][key] = value
            with self.subTest(key=key, value=value):
                self.assertFalse(mistral_qualification_pilot_admission(**p))

    def test_no_inference_evidence_no_unattended_worker_no_pilot(self):
        mutations = (
            ("actor_record", "enabled", False),
            ("actor_record", "configured", False),
            ("actor_record", "cost_class", "METERED_ALLOWED"),
            ("actor_record", "permissions", ["read", "write"]),
            ("ready", "setup_state", "not_started"),
            ("ready", "verified_surfaces", []),
            ("ready", "verified_capabilities", []),
            ("ready", "verified_capabilities", ["implementation"]),
            ("ready", "repository_access", {}),
            ("ready", "unattended", {}),
            ("ready", "capacity", {"implementation_streams": 5}),
        )
        for owner, field, value in mutations:
            p = self.policy()
            p[owner][field] = value
            with self.subTest(owner=owner, field=field):
                self.assertFalse(mistral_qualification_pilot_admission(**p))

    def test_paid_fallback_and_emergency_stop_always_refused(self):
        for field, value in (
            ("allow_paid_fallback", True),
            ("allow_overage", True),
            ("allow_auto_topup", True),
            ("allow_new_paid_vendor", True),
            ("additional_monthly_spend_cap", 1),
            ("additional_monthly_spend_cap", True),
            ("unknown_cost_behavior", "allow"),
        ):
            p = self.policy()
            p["budget"]["ai"][field] = value
            with self.subTest(field=field):
                self.assertFalse(mistral_qualification_pilot_admission(**p))
        p = self.policy()
        p["config"]["safety"]["emergency_stop"] = True
        self.assertFalse(mistral_qualification_pilot_admission(**p))


if __name__ == "__main__":
    unittest.main()
