from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTROL = ROOT / ".onecompany"
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import simulate as simulate_script  # noqa: E402


def load(name: str) -> dict:
    return json.loads((CONTROL / name).read_text(encoding="utf-8"))


class InteractiveActivationTests(unittest.TestCase):
    def test_only_evidence_backed_actors_are_enabled(self):
        actors = load("actors.json")["actors"]
        enabled = {item["id"] for item in actors if item.get("enabled")}
        configured = {item["id"] for item in actors if item.get("configured")}
        expected = {"human-owner", "chatgpt", "onecompany-local", "grok-4-6-interactive", "mistral-vibe"}
        self.assertEqual(enabled, expected)
        self.assertEqual(configured, expected)

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

        local = readiness["onecompany-local"]
        self.assertEqual(local["setup_state"], "ready")
        self.assertEqual(local["verified_capabilities"], ["repository_intelligence"])
        self.assertTrue(local["repository_access"]["read"])
        self.assertFalse(local["repository_access"]["write"])
        self.assertFalse(local["repository_access"]["review"])
        self.assertFalse(local["repository_access"]["merge"])
        self.assertEqual(local["capacity"]["implementation_streams"], 0)
        self.assertTrue(local["capacity"]["measured"])
        self.assertTrue(local["capacity"]["evidence"])

        grok = readiness["grok-4-6-interactive"]
        self.assertEqual(grok["setup_state"], "ready")
        self.assertEqual(grok["verified_capabilities"], ["repository_intelligence"])
        self.assertTrue(grok["repository_access"]["read"])
        self.assertFalse(grok["repository_access"]["write"])
        self.assertFalse(grok["repository_access"]["review"])
        self.assertFalse(grok["repository_access"]["merge"])
        self.assertEqual(grok["capacity"]["implementation_streams"], 0)
        self.assertTrue(grok["capacity"]["measured"])
        self.assertTrue(grok["capacity"]["evidence"])
        self.assertTrue(grok["evidence"])

        mistral = readiness["mistral-vibe"]
        self.assertEqual(mistral["setup_state"], "ready")
        self.assertEqual(mistral["verified_capabilities"],
                         ["repository_intelligence", "test_design"])
        self.assertTrue(mistral["repository_access"]["read"])
        for prohibited in ("write", "review", "merge"):
            self.assertFalse(mistral["repository_access"][prohibited])
        self.assertEqual(mistral["capacity"]["implementation_streams"], 0)
        self.assertIn("35540501655", " ".join(mistral["evidence"]))
        self.assertTrue(mistral["unattended"]["verified"])

        for actor_id, actor in actors.items():
            if actor_id in {"human-owner", "chatgpt", "onecompany-local", "grok-4-6-interactive", "mistral-vibe"}:
                continue
            self.assertFalse(actor["enabled"], actor_id)
            self.assertFalse(actor["configured"], actor_id)
            self.assertEqual(readiness[actor_id]["setup_state"], "not_started")
            self.assertEqual(readiness[actor_id]["verified_capabilities"], [])

    def test_verified_capability_requires_configured_dispatch_mechanism(self):
        actors = load("actors.json")
        readiness = load("readiness.json")
        dispatch = load("dispatch.json")
        self.assertTrue(
            simulate_script.verified_capabilities_have_configured_dispatch(
                actors,
                readiness,
                dispatch,
            )
        )

        inconsistent_dispatch = copy.deepcopy(dispatch)
        chatgpt = next(
            item
            for item in inconsistent_dispatch["actors"]
            if item["actor_id"] == "chatgpt"
        )
        interactive = next(
            item
            for item in chatgpt["mechanisms"]
            if item["id"] == "interactive-connected-chat"
        )
        interactive["capabilities"] = [
            capability
            for capability in interactive["capabilities"]
            if capability != "implementation"
        ]

        self.assertFalse(
            simulate_script.verified_capabilities_have_configured_dispatch(
                actors,
                readiness,
                inconsistent_dispatch,
            )
        )

    def test_enabled_actor_requires_usable_readiness_before_dispatch_coverage(self):
        actors = load("actors.json")
        readiness = load("readiness.json")
        dispatch = load("dispatch.json")

        missing_readiness = copy.deepcopy(readiness)
        missing_readiness["actors"] = [
            item
            for item in missing_readiness["actors"]
            if item["actor_id"] != "chatgpt"
        ]
        self.assertFalse(
            simulate_script.verified_capabilities_have_configured_dispatch(
                actors,
                missing_readiness,
                dispatch,
            )
        )

        empty_readiness = copy.deepcopy(readiness)
        chatgpt = next(
            item
            for item in empty_readiness["actors"]
            if item["actor_id"] == "chatgpt"
        )
        chatgpt["verified_capabilities"] = []
        self.assertFalse(
            simulate_script.verified_capabilities_have_configured_dispatch(
                actors,
                empty_readiness,
                dispatch,
            )
        )

    def test_only_verified_readonly_a3b_path_is_unattended(self):
        readiness = {item["actor_id"]: item for item in load("readiness.json")["actors"]}
        dispatch = {item["actor_id"]: item for item in load("dispatch.json")["actors"]}

        for actor_id, record in readiness.items():
            unattended = record["unattended"]
            if actor_id in {"onecompany-local", "mistral-vibe"}:
                self.assertTrue(unattended["configured"])
                self.assertTrue(unattended["verified"])
            else:
                self.assertFalse(unattended["configured"], actor_id)
                self.assertFalse(unattended["verified"], actor_id)

        configured_unattended = [
            (actor_id, mechanism["id"])
            for actor_id, record in dispatch.items()
            for mechanism in record.get("mechanisms", [])
            if mechanism.get("configured") and mechanism.get("unattended")
        ]
        self.assertEqual(
            configured_unattended,
            [
                ("onecompany-local", "onecompany-actions-readonly"),
                ("mistral-vibe", "vibe-readonly-wake"),
            ],
        )

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
