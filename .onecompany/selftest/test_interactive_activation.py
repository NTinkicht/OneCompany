from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTROL = ROOT / ".onecompany"


def load(name: str) -> dict:
    return json.loads((CONTROL / name).read_text(encoding="utf-8"))


class InteractiveActivationTests(unittest.TestCase):
    def test_only_human_owner_and_chatgpt_are_enabled(self):
        actors = load("actors.json")["actors"]
        enabled = {item["id"] for item in actors if item.get("enabled")}
        configured = {item["id"] for item in actors if item.get("configured")}
        self.assertEqual(enabled, {"human-owner", "chatgpt"})
        self.assertEqual(configured, {"human-owner", "chatgpt"})

    def test_readiness_is_evidence_backed_and_capacity_is_conservative(self):
        actors = {item["id"]: item for item in load("actors.json")["actors"]}
        readiness = {item["actor_id"]: item for item in load("readiness.json")["actors"]}

        human = readiness["human-owner"]
        self.assertEqual(human["setup_state"], "ready")
        self.assertTrue(human["repository_access"]["review"])
        self.assertTrue(human["repository_access"]["merge"])
        self.assertNotIn("implementation", human["verified_capabilities"])
        self.assertEqual(human["capacity"]["implementation_streams"], 0)
        self.assertTrue(human["capacity"]["measured"])
        self.assertTrue(human["evidence"])

        chatgpt = readiness["chatgpt"]
        self.assertEqual(chatgpt["setup_state"], "ready")
        self.assertIn("implementation", chatgpt["verified_capabilities"])
        self.assertTrue(chatgpt["repository_access"]["write"])
        self.assertEqual(chatgpt["capacity"]["implementation_streams"], 1)
        self.assertTrue(chatgpt["capacity"]["measured"])
        self.assertTrue(chatgpt["capacity"]["evidence"])

        for actor_id, actor in actors.items():
            if actor_id in {"human-owner", "chatgpt"}:
                continue
            self.assertFalse(actor["enabled"], actor_id)
            self.assertFalse(actor["configured"], actor_id)
            self.assertEqual(readiness[actor_id]["setup_state"], "not_started")
            self.assertEqual(readiness[actor_id]["verified_capabilities"], [])

    def test_no_unattended_path_is_activated(self):
        readiness = {item["actor_id"]: item for item in load("readiness.json")["actors"]}
        dispatch = {item["actor_id"]: item for item in load("dispatch.json")["actors"]}

        for actor_id, record in readiness.items():
            unattended = record["unattended"]
            self.assertFalse(unattended["configured"], actor_id)
            self.assertFalse(unattended["verified"], actor_id)

        configured_unattended = [
            (actor_id, mechanism["id"])
            for actor_id, record in dispatch.items()
            for mechanism in record.get("mechanisms", [])
            if mechanism.get("configured") and mechanism.get("unattended")
        ]
        self.assertEqual(configured_unattended, [])

    def test_chatgpt_interactive_implementation_dispatch_is_ready(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "dispatch.py"),
                "--actor",
                "chatgpt",
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
        self.assertEqual(payload["status"], "DISPATCH_READY")
        self.assertEqual(
            [item["id"] for item in payload["mechanisms"]],
            ["interactive-connected-chat"],
        )
        self.assertFalse(payload["mechanisms"][0]["unattended"])

    def test_chatgpt_unattended_implementation_remains_blocked(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "dispatch.py"),
                "--actor",
                "chatgpt",
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
        self.assertEqual(payload["status"], "CAPACITY_BLOCKED")
        self.assertIn("unattended_readiness_not_verified", payload["reasons"])
        self.assertIn("no_configured_execution_mechanism", payload["reasons"])

    def test_human_owner_is_not_routine_implementation_capacity(self):
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "dispatch.py"),
                "--actor",
                "human-owner",
                "--capability",
                "implementation",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(completed.returncode, 0)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "CAPACITY_BLOCKED")
        self.assertIn("capability_not_verified", payload["reasons"])


if __name__ == "__main__":
    unittest.main()
