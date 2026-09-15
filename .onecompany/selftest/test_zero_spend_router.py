from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import router  # noqa: E402


class ZeroSpendRouterTests(unittest.TestCase):
    """Regress the A2 routing boundary without creating coordination authority."""

    def test_current_interactive_implementation_route_is_dispatchable(self):
        """A1's only verified writer must be a real interactive route, not phantom readiness."""
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "onecompany.py"),
                "route",
                "--capability",
                "implementation",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "ROUTE_READY")
        self.assertEqual(payload["proposed_actor"], "chatgpt")
        self.assertIsNone(payload["failover"])

    def test_unattended_route_remains_fail_closed(self):
        """A2 must not turn interactive readiness into unattended authority."""
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "onecompany.py"),
                "route",
                "--capability",
                "implementation",
                "--unattended",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "BLOCKED_NO_ELIGIBLE_ROUTE")
        self.assertEqual(payload["eligible"], [])

    def test_dispatch_gap_is_a_hard_filter_for_interactive_routes(self):
        """Verified capability alone is insufficient when no execution mechanism exists."""
        dispatch = {
            "actors": [
                {
                    "actor_id": "worker",
                    "mechanisms": [
                        {
                            "id": "interactive",
                            "configured": True,
                            "unattended": False,
                            "capabilities": ["planning"],
                        }
                    ],
                }
            ]
        }
        self.assertEqual(
            router.dispatch_gaps(dispatch, "worker", {"implementation"}, False),
            ["implementation"],
        )
        self.assertEqual(
            router.dispatch_gaps(dispatch, "worker", {"planning"}, False),
            [],
        )
        self.assertEqual(
            router.dispatch_gaps(dispatch, "worker", {"planning"}, True),
            ["planning"],
        )

    def test_failover_requires_canonical_active_source_and_allowlisted_trigger(self):
        """A timer string or stale lease ID must never authorize a competing writer."""
        active = [
            {
                "id": "lease-1",
                "role": "implementation",
                "actor": "chatgpt",
                "work_unit": "WU-X",
            }
        ]
        source, reasons = router.failover_context(
            active,
            "lease-1",
            "heartbeat_stale",
            {"implementation"},
        )
        self.assertIsNotNone(source)
        self.assertIn("failover_trigger_not_allowed", reasons)

        source, reasons = router.failover_context(
            active,
            "missing",
            "quota_exhausted",
            {"implementation"},
        )
        self.assertIsNone(source)
        self.assertIn("failover_source_lease_not_active", reasons)

        source, reasons = router.failover_context(
            active,
            "lease-1",
            "quota_exhausted",
            {"implementation"},
        )
        self.assertEqual(source["actor"], "chatgpt")
        self.assertEqual(reasons, [])

    def test_failover_proposal_never_applies_to_nonimplementation_capability(self):
        """Review or planning routing cannot smuggle an implementation-lease transfer."""
        source, reasons = router.failover_context(
            [{"id": "lease-1", "role": "implementation", "actor": "chatgpt"}],
            "lease-1",
            "human_override",
            {"code_review"},
        )
        self.assertIsNotNone(source)
        self.assertIn("failover_requires_implementation_capability", reasons)

    def test_failover_trigger_set_excludes_timer_and_heartbeat_only_signals(self):
        """Only reconciled operational triggers may be proposed for same-stream failover."""
        self.assertNotIn("timer_expired", router.FAILOVER_TRIGGERS)
        self.assertNotIn("heartbeat_stale", router.FAILOVER_TRIGGERS)
        self.assertIn("no_progress_after_reconcile", router.FAILOVER_TRIGGERS)
        self.assertIn("human_override", router.FAILOVER_TRIGGERS)


if __name__ == "__main__":
    unittest.main()
