from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class A3bSpendBoundaryTests(unittest.TestCase):
    """Regress that A3b adds execution capacity without spend or write expansion."""

    def load_json(self, relative: str):
        return json.loads((ROOT / relative).read_text(encoding="utf-8"))

    def test_budget_remains_zero_extra_spend(self):
        budget = self.load_json(".onecompany/budget.json")
        ai = budget["ai"]
        self.assertEqual(ai["additional_monthly_spend_cap"], 0)
        self.assertFalse(ai["allow_paid_fallback"])
        self.assertFalse(ai["allow_overage"])
        self.assertFalse(ai["allow_auto_topup"])
        self.assertFalse(ai["allow_new_paid_vendor"])

    def test_new_worker_has_no_write_review_merge_or_implementation_authority(self):
        actors = {item["id"]: item for item in self.load_json(".onecompany/actors.json")["actors"]}
        readiness = {item["actor_id"]: item for item in self.load_json(".onecompany/readiness.json")["actors"]}
        local = actors["onecompany-local"]
        ready = readiness["onecompany-local"]
        self.assertNotIn("implementation", local["capabilities"])
        self.assertNotIn("ci_remediation", local["capabilities"])
        self.assertNotIn("merge_execution", local["capabilities"])
        self.assertEqual(local["permissions"], ["read"])
        self.assertFalse(ready["repository_access"]["write"])
        self.assertFalse(ready["repository_access"]["review"])
        self.assertFalse(ready["repository_access"]["merge"])
        self.assertEqual(ready["capacity"]["implementation_streams"], 0)


if __name__ == "__main__":
    unittest.main()
