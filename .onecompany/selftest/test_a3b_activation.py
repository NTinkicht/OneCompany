from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import dispatch  # noqa: E402
import dispatch_execute_entry  # noqa: E402
import local_actions_adapter  # noqa: E402


class A3bActivationTests(unittest.TestCase):
    """Regress evidence-backed activation without widening write authority."""

    def load_control(self, name: str):
        return json.loads((ROOT / ".onecompany" / name).read_text(encoding="utf-8"))

    def test_local_worker_is_the_only_new_verified_unattended_actor(self):
        actors = {item["id"]: item for item in self.load_control("actors.json")["actors"]}
        readiness = {item["actor_id"]: item for item in self.load_control("readiness.json")["actors"]}
        mechanisms = {item["actor_id"]: item for item in self.load_control("dispatch.json")["actors"]}

        local = actors["onecompany-local"]
        self.assertTrue(local["enabled"])
        self.assertTrue(local["configured"])
        self.assertEqual(local["cost_class"], "FREE_ALLOWANCE")
        self.assertEqual(local["permissions"], ["read"])
        self.assertEqual(local["capabilities"], ["repository_intelligence"])

        ready = readiness["onecompany-local"]
        self.assertEqual(ready["setup_state"], "ready")
        self.assertEqual(ready["verified_capabilities"], ["repository_intelligence"])
        self.assertEqual(
            ready["repository_access"],
            {"read": True, "write": False, "review": False, "merge": False},
        )
        self.assertEqual(ready["unattended"], {"configured": True, "verified": True})
        self.assertEqual(ready["capacity"]["implementation_streams"], 0)
        self.assertTrue(any("35026542482" in item for item in ready["evidence"] + ready["capacity"]["evidence"]))

        configured = [
            item
            for item in mechanisms["onecompany-local"]["mechanisms"]
            if item.get("configured") is True
        ]
        self.assertEqual(len(configured), 1)
        self.assertEqual(configured[0]["id"], "onecompany-actions-readonly")
        self.assertTrue(configured[0]["unattended"])
        self.assertEqual(configured[0]["capabilities"], ["repository_intelligence"])

    def test_copilot_remains_disabled_after_quota_probe(self):
        actors = {item["id"]: item for item in self.load_control("actors.json")["actors"]}
        readiness = {item["actor_id"]: item for item in self.load_control("readiness.json")["actors"]}
        mechanisms = {item["actor_id"]: item for item in self.load_control("dispatch.json")["actors"]}

        self.assertFalse(actors["github-copilot"]["enabled"])
        self.assertFalse(actors["github-copilot"]["configured"])
        self.assertEqual(readiness["github-copilot"]["setup_state"], "not_started")
        self.assertFalse(readiness["github-copilot"]["unattended"]["verified"])
        copilot_a3b = next(
            item
            for item in mechanisms["github-copilot"]["mechanisms"]
            if item["id"] == "copilot-actions-readonly"
        )
        self.assertFalse(copilot_a3b["configured"])
        self.assertTrue(any("quota" in item.lower() for item in copilot_a3b["evidence"]))

    def test_unattended_repository_intelligence_resolves_to_exact_local_mechanism(self):
        with patch.object(dispatch, "emergency_stop_active", return_value=False):
            result = dispatch.resolve_dispatch(
                "onecompany-local",
                "repository_intelligence",
                unattended=True,
            )
        self.assertEqual(result["status"], "DISPATCH_READY")
        self.assertEqual([item["id"] for item in result["mechanisms"]], ["onecompany-actions-readonly"])

    def test_local_worker_cannot_resolve_implementation(self):
        with patch.object(dispatch, "emergency_stop_active", return_value=False):
            result = dispatch.resolve_dispatch(
                "onecompany-local",
                "implementation",
                unattended=True,
            )
        self.assertEqual(result["status"], "CAPACITY_BLOCKED")
        self.assertIn("capability_not_declared", result["reasons"])
        self.assertIn("capability_not_verified", result["reasons"])
        self.assertIn("no_configured_execution_mechanism", result["reasons"])

    def test_ledger_activation_failure_preserves_capacity_blocked_contract(self):
        with (
            patch.object(dispatch, "emergency_stop_active", return_value=False),
            patch.object(
                dispatch,
                "ledger_enabled",
                side_effect=RuntimeError("protected-tip-mismatch"),
            ),
        ):
            result = dispatch.resolve_dispatch(
                "onecompany-local",
                "implementation",
                unattended=True,
                lease_id="lease-not-used",
            )
        self.assertEqual(result["status"], "CAPACITY_BLOCKED")
        self.assertIn(
            "ledger_unavailable:protected-tip-mismatch",
            result["reasons"],
        )

    def test_entrypoint_registers_only_reviewed_a3b_mechanisms(self):
        self.assertIs(
            dispatch_execute_entry.ADAPTERS["onecompany-actions-readonly"],
            local_actions_adapter.invoke,
        )
        self.assertIn("copilot-actions-readonly", dispatch_execute_entry.ADAPTERS)
        self.assertNotIn("interactive-connected-chat", dispatch_execute_entry.ADAPTERS)


if __name__ == "__main__":
    unittest.main()
