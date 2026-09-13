from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from capacity_lib import implementation_availability, implementation_pool
from supervise import decide_ready_work_action


class CapacityAndSupervisionTests(unittest.TestCase):
    def actor(self, actor_id="worker"):
        return {
            "id": actor_id,
            "enabled": True,
            "configured": True,
            "cost_class": "INCLUDED_SUBSCRIPTION",
            "capabilities": ["implementation"],
        }

    def ready(self, actor_id="worker", capacity=2, unattended=False):
        return {
            "actor_id": actor_id,
            "setup_state": "ready",
            "verified_capabilities": ["implementation"],
            "temporarily_unavailable_capabilities": [],
            "repository_access": {"read": True, "write": True},
            "capacity": {
                "implementation_streams": capacity,
                "measured": True,
                "observed_at": "2026-09-13T00:00:00Z",
                "evidence": ["selftest:measured-capacity-fixture"],
            },
            "unattended": {"configured": unattended, "verified": unattended},
        }

    def budget(self):
        return {
            "ai": {"additional_monthly_spend_cap": 0, "allow_paid_fallback": False},
            "cost_classes": {
                "allowed": ["INCLUDED_SUBSCRIPTION", "FREE_ALLOWANCE", "LOCAL", "HUMAN"],
                "conditionally_allowed": [],
                "forbidden": ["METERED_ALLOWED", "METERED_FORBIDDEN", "UNKNOWN_COST"],
            },
        }

    def dispatch(self, configured=True):
        return {
            "actors": [{
                "actor_id": "worker",
                "mechanisms": [{
                    "id": "worker-runner",
                    "configured": configured,
                    "unattended": True,
                    "capabilities": ["implementation"],
                }],
            }],
        }

    def test_capacity_subtracts_active_streams(self):
        active = [{"id": "L1", "role": "implementation", "actor": "worker"}]
        slots, reasons = implementation_availability(
            self.actor(), self.ready(capacity=2), self.budget(), active
        )
        self.assertEqual(slots, 1)
        self.assertNotIn("actor_capacity", reasons)

    def test_interactive_ready_does_not_imply_unattended_ready(self):
        slots, _ = implementation_availability(
            self.actor(), self.ready(unattended=False), self.budget(), []
        )
        unattended_slots, reasons = implementation_availability(
            self.actor(),
            self.ready(unattended=False),
            self.budget(),
            [],
            dispatch_doc=self.dispatch(),
            require_unattended=True,
        )
        self.assertEqual(slots, 2)
        self.assertEqual(unattended_slots, 0)
        self.assertIn("unattended_not_verified", reasons)

    def test_unattended_requires_configured_dispatch(self):
        slots, reasons = implementation_availability(
            self.actor(),
            self.ready(unattended=True),
            self.budget(),
            [],
            dispatch_doc=self.dispatch(configured=False),
            require_unattended=True,
        )
        self.assertEqual(slots, 0)
        self.assertIn("unattended_implementation_dispatch_missing", reasons)

    def test_pool_sums_only_eligible_capacity(self):
        actors = {"actors": [self.actor("worker"), self.actor("blocked")]}
        readiness = {"actors": [self.ready("worker", capacity=2), self.ready("blocked", capacity=4)]}
        readiness["actors"][1]["temporarily_unavailable_capabilities"] = ["implementation"]
        result = implementation_pool(actors, readiness, self.budget(), [])
        self.assertEqual(result["free_slots"], 2)
        self.assertEqual(result["actors"], [{"actor": "worker", "free_slots": 2}])

    def test_l2_ready_work_requires_authority(self):
        decision = decide_ready_work_action(["WU-1"], 0, False, 3)
        self.assertIsNotNone(decision)
        self.assertEqual(decision[0], "READY_WORK_REQUIRES_AUTHORITY")
        self.assertEqual(decision[2], [])

    def test_l4_without_unattended_capacity_is_capacity_blocked(self):
        decision = decide_ready_work_action(["WU-1"], 0, True, 0)
        self.assertIsNotNone(decision)
        self.assertEqual(decision[0], "CAPACITY_BLOCKED")
        self.assertEqual(decision[2], [])

    def test_l4_caps_start_candidates_to_verified_capacity(self):
        decision = decide_ready_work_action(["WU-1", "WU-2"], 0, True, 1)
        self.assertIsNotNone(decision)
        self.assertEqual(decision[0], "START_READY_WORK")
        self.assertEqual(decision[2], ["WU-1"])

    def test_existing_stream_uses_parallel_start_state(self):
        decision = decide_ready_work_action(["WU-2"], 1, True, 1)
        self.assertIsNotNone(decision)
        self.assertEqual(decision[0], "START_PARALLEL_READY_WORK")


if __name__ == "__main__":
    unittest.main()
