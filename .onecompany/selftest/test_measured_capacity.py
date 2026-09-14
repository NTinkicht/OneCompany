from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import capacity_lib


class MeasuredCapacityTests(unittest.TestCase):
    def ready(self, *, measured: bool, streams: int, evidence=None, observed_at=None):
        return {
            "setup_state": "ready",
            "verified_capabilities": ["implementation"],
            "temporarily_unavailable_capabilities": [],
            "repository_access": {"read": True, "write": True, "review": False, "merge": False},
            "unattended": {"configured": False, "verified": False},
            "capacity": {
                "implementation_streams": streams,
                "measured": measured,
                "observed_at": observed_at,
                "evidence": evidence or [],
            },
        }

    def actor(self, cost_class="FREE_ALLOWANCE"):
        return {
            "id": "worker",
            "enabled": True,
            "configured": True,
            "capabilities": ["implementation"],
            "cost_class": cost_class,
        }

    def budget(self):
        return {
            "cost_classes": {
                "allowed": ["FREE_ALLOWANCE", "LOCAL", "INCLUDED_SUBSCRIPTION", "HUMAN"],
                "conditionally_allowed": [],
                "forbidden": ["METERED_ALLOWED", "METERED_FORBIDDEN", "UNKNOWN_COST"],
            }
        }

    def test_unmeasured_configured_number_grants_zero_slots(self):
        ready = self.ready(measured=False, streams=8)
        slots, reasons = capacity_lib.implementation_availability(
            self.actor(), ready, self.budget(), []
        )
        self.assertEqual(slots, 0)
        self.assertIn("capacity_unmeasured", reasons)
        self.assertIn("capacity_observed_at_missing", reasons)
        self.assertIn("capacity_evidence_missing", reasons)

    def test_measured_evidenced_capacity_is_used_as_circuit_breaker(self):
        ready = self.ready(
            measured=True,
            streams=2,
            evidence=["probe:github-session-2026-09-14"],
            observed_at="2026-09-14T00:00:00Z",
        )
        active = [{"id": "L1", "role": "implementation", "actor": "worker"}]
        slots, reasons = capacity_lib.implementation_availability(
            self.actor(), ready, self.budget(), active
        )
        self.assertEqual(slots, 1)
        self.assertNotIn("actor_capacity", reasons)

    def test_capacity_never_overrides_zero_spend_budget(self):
        ready = self.ready(
            measured=True,
            streams=10,
            evidence=["probe:metered-worker"],
            observed_at="2026-09-14T00:00:00Z",
        )
        slots, reasons = capacity_lib.implementation_availability(
            self.actor("METERED_ALLOWED"), ready, self.budget(), []
        )
        self.assertEqual(slots, 0)
        self.assertIn("forbidden_by_budget", reasons)

    def test_missing_measurement_evidence_fails_closed(self):
        ready = self.ready(
            measured=True,
            streams=2,
            evidence=[],
            observed_at="2026-09-14T00:00:00Z",
        )
        self.assertEqual(capacity_lib.implementation_capacity_limit(ready), 0)
        self.assertIn("capacity_evidence_missing", capacity_lib.capacity_measurement_errors(ready))


if __name__ == "__main__":
    unittest.main()
