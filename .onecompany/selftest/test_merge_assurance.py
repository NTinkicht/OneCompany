from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import merge

HEAD = "a" * 40
BASE = "b" * 40


class MergeAssuranceTests(unittest.TestCase):
    def state(self) -> dict:
        gate = {
            "verdict": "PASS — MERGE_READY",
            "stale": False,
            "work_unit": "WU900",
            "material_authors": ["implementer-example"],
            "reviewer_actor": "reviewer-example",
            "evidence": ["review://exact-head"],
            "scope_verified": True,
            "sha": HEAD,
            "base_sha": BASE,
        }
        return {
            "open_blockers": [],
            "human_decision_required": False,
            "active_leases": [],
            "active_streams": [
                {
                    "pr": 1,
                    "work_unit": "WU900",
                    "gate": gate,
                    "material_authors": ["implementer-example"],
                    "open_blockers": [],
                    "human_decision_required": False,
                }
            ],
        }

    def queue(self) -> dict:
        return {
            "work_units": [
                {
                    "id": "WU900",
                    "pr": 1,
                    "branch": "wu-900",
                    "write_scope": ["**/*"],
                }
            ]
        }

    def live(self) -> dict:
        return {
            "state": "OPEN",
            "isDraft": False,
            "headRefOid": HEAD,
            "baseRefOid": BASE,
        }

    def patch_environment(self, state: dict, *, run_side_effect=None):
        config = {
            "project": {"repository": "owner/repo"},
            "autonomy": {"level": "L2"},
        }

        def fake_load(path: Path):
            name = Path(path).name
            if name == "config.json":
                return config
            if name == "state.json":
                return state
            if name == "queue.json":
                return self.queue()
            raise AssertionError(f"unexpected load_json: {path}")

        if run_side_effect is None:
            run_side_effect = lambda command, cwd=None: subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        return (
            patch.object(merge, "emergency_stop_active", return_value=False),
            patch.object(merge, "command_exists", return_value=True),
            patch.object(merge, "run", side_effect=run_side_effect),
            patch.object(merge, "load_json", side_effect=fake_load),
            patch.object(merge, "governance_config", return_value={"control_plane": {"fail_closed_if_diff_unavailable": True, "human_merge_required": False}}),
            patch.object(merge, "changed_files", return_value=(["src/change.py"], None)),
            patch.object(merge, "protected_control_plane_paths", return_value=[]),
            patch.object(merge, "always_human_paths", return_value=[]),
            patch.object(merge, "ledger_enabled", return_value=False),
            patch.object(merge, "scope_errors", return_value=[]),
            patch.object(merge, "capability_eligible", return_value=(True, [])),
            patch.object(merge, "live_pr", return_value=(self.live(), None)),
            patch.object(merge, "evaluate_required_checks", return_value=(True, [], [])),
            patch.object(merge, "save_json"),
        )

    def test_merge_refuses_without_assurance_packet(self):
        state = self.state()
        patches = self.patch_environment(state)
        with patches[0], patches[1], patches[2] as run_mock, patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], patches[11], patches[12], patch.object(sys, "argv", ["merge.py", "--actor", "human-owner", "--pr", "1"]):
            result = merge.main()
        self.assertEqual(result, 2)
        self.assertEqual(run_mock.call_count, 1, "only gh auth status may run; merge mutation must not execute")

    def test_unverified_assurance_refuses_before_merge_mutation(self):
        state = self.state()
        patches = self.patch_environment(state)
        with patches[0], patches[1], patches[2] as run_mock, patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], patches[11], patches[12], patch.object(merge, "validate_structure", return_value=([], [])), patch.object(merge, "verify_trusted_packet", return_value=({"verdict": "UNVERIFIED"}, ["artifact failed"])), patch.object(sys, "argv", ["merge.py", "--actor", "human-owner", "--pr", "1", "--assurance-packet", ".onecompany/reference/assurance/WU900.json"]):
            result = merge.main()
        self.assertEqual(result, 2)
        self.assertEqual(run_mock.call_count, 1, "unverified assurance must block before GitHub merge mutation")

    def test_pass_attestation_allows_exact_head_merge(self):
        state = self.state()

        def fake_run(command, cwd=None):
            if command[:3] == ["gh", "auth", "status"]:
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
            if command[:4] == ["gh", "api", "--method", "PUT"]:
                return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"merged": True, "sha": "c" * 40}), stderr="")
            raise AssertionError(f"unexpected command: {command}")

        patches = self.patch_environment(state, run_side_effect=fake_run)
        attestation = {
            "verdict": "PASS",
            "policy_revision": "quality:q;required-checks:r",
            "head_sha": HEAD,
            "base_sha": BASE,
        }
        with patches[0], patches[1], patches[2] as run_mock, patches[3], patches[4], patches[5], patches[6], patches[7], patches[8], patches[9], patches[10], patches[11], patches[12], patch.object(merge, "validate_structure", return_value=([], [])), patch.object(merge, "verify_trusted_packet", return_value=(attestation, [])), patch.object(sys, "argv", ["merge.py", "--actor", "human-owner", "--pr", "1", "--assurance-packet", ".onecompany/reference/assurance/WU900.json"]):
            result = merge.main()
        self.assertEqual(result, 0)
        self.assertEqual(run_mock.call_count, 2)
        self.assertEqual(state["last_merge"]["approved_head"], HEAD)
        self.assertEqual(state["last_merge"]["approved_base"], BASE)
        self.assertEqual(len(state["last_merge"]["assurance_attestation_sha256"]), 64)
        self.assertEqual(state["last_merge"]["assurance_policy_revision"], attestation["policy_revision"])


if __name__ == "__main__":
    unittest.main()
