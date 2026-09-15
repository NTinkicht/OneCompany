from __future__ import annotations

import json
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

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

    def test_zero_spend_filter_rejects_conditional_and_unknown_cost_classes(self):
        """Positive caps or permissive unknown-cost settings must not escape A2 zero-spend routing."""
        budget = {
            "ai": {
                "additional_monthly_spend_cap": 100,
                "unknown_cost_behavior": "allow_within_cap",
            },
            "cost_classes": {
                "allowed": ["INCLUDED_SUBSCRIPTION"],
                "conditionally_allowed": ["METERED_ALLOWED"],
                "forbidden": [],
            },
        }
        self.assertTrue(router.zero_spend_budget_allows("INCLUDED_SUBSCRIPTION", budget))
        self.assertFalse(router.zero_spend_budget_allows("METERED_ALLOWED", budget))
        self.assertFalse(router.zero_spend_budget_allows("UNKNOWN_COST", budget))

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

    def test_valid_failover_routes_through_main_to_different_actor(self):
        """A valid failover CLI proposal excludes its source actor and reports replacement capacity."""
        docs = {
            "actors.json": {
                "actors": [
                    {
                        "id": "source",
                        "enabled": True,
                        "configured": True,
                        "capabilities": ["implementation"],
                        "cost_class": "INCLUDED_SUBSCRIPTION",
                    },
                    {
                        "id": "replacement",
                        "enabled": True,
                        "configured": True,
                        "capabilities": ["implementation"],
                        "cost_class": "INCLUDED_SUBSCRIPTION",
                    },
                ]
            },
            "readiness.json": {
                "actors": [
                    {
                        "actor_id": actor_id,
                        "setup_state": "ready",
                        "verified_capabilities": ["implementation"],
                        "temporarily_unavailable_capabilities": [],
                        "repository_access": {
                            "read": True,
                            "write": True,
                            "review": False,
                            "merge": False,
                        },
                    }
                    for actor_id in ("source", "replacement")
                ]
            },
            "routing.json": {"preference_by_capability": {"implementation": ["source", "replacement"]}},
            "dispatch.json": {
                "actors": [
                    {
                        "actor_id": actor_id,
                        "mechanisms": [
                            {
                                "id": "interactive",
                                "configured": True,
                                "unattended": False,
                                "capabilities": ["implementation"],
                            }
                        ],
                    }
                    for actor_id in ("source", "replacement")
                ]
            },
            "budget.json": {
                "cost_classes": {
                    "allowed": ["INCLUDED_SUBSCRIPTION"],
                    "conditionally_allowed": [],
                    "forbidden": ["UNKNOWN_COST"],
                }
            },
        }
        view = {
            "active_leases": [
                {
                    "id": "lease-1",
                    "role": "implementation",
                    "actor": "source",
                    "work_unit": "WU-X",
                }
            ],
            "material_authors": [],
        }

        def fake_load(path: Path) -> dict:
            return docs[path.name]

        def fake_availability(actor, status, budget, active, **kwargs):
            self.assertEqual(kwargs.get("exclude_lease_id"), "lease-1")
            return 1, []

        output = StringIO()
        argv = [
            "router.py",
            "--capability",
            "implementation",
            "--replace-lease-id",
            "lease-1",
            "--failover-trigger",
            "quota_exhausted",
        ]
        with (
            mock.patch.object(router, "load_json", side_effect=fake_load),
            mock.patch.object(router, "coordination_view", return_value=view),
            mock.patch.object(router, "implementation_availability", side_effect=fake_availability),
            mock.patch.object(sys, "argv", argv),
            redirect_stdout(output),
        ):
            rc = router.main()

        payload = json.loads(output.getvalue())
        self.assertEqual(rc, 0)
        self.assertEqual(payload["status"], "ROUTE_READY")
        self.assertEqual(payload["proposed_actor"], "replacement")
        self.assertNotEqual(payload["proposed_actor"], payload["failover"]["source_actor"])
        self.assertEqual(payload["eligible"][0]["free_implementation_slots"], 1)
        self.assertEqual(payload["failover"]["source_lease_id"], "lease-1")

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
