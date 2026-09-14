from __future__ import annotations

import json
import subprocess
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import merge

HEAD = "a" * 40
BASE = "b" * 40


class MergeAssuranceTests(unittest.TestCase):
    def gate(self) -> dict:
        return {
            "verdict": "PASS — MERGE_READY",
            "stale": False,
            "work_unit": "WU900",
            "material_authors": ["implementer-example"],
            "reviewer_actor": "codex",
            "reviewer_login": "review-bot",
            "review_id": 42,
            "evidence": ["review://exact-head"],
            "scope_verified": True,
            "sha": HEAD,
            "base_sha": BASE,
        }

    def active_lease(self) -> dict:
        return {
            "id": "L-WU900",
            "role": "implementation",
            "actor": "implementer-example",
            "work_unit": "WU900",
            "branch": "wu-900",
            "pr": 1,
            "start_head": HEAD,
            "status": "active",
        }

    def coordination(self) -> dict:
        gate = self.gate()
        return {
            "active_leases": [self.active_lease()],
            "material_authors": ["implementer-example"],
            "current_gate": gate,
            "gates_by_pr": {1: gate},
            "integrity_conflicts": [],
            "rejected_claims": [],
            "current_actor_eligibility": {},
        }

    def state(self) -> dict:
        gate = self.gate()
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
            "baseRefName": "main",
        }

    def packet(self) -> dict:
        return {
            "status": "merge_ready",
            "work_unit": "WU900",
            "candidate_sha": HEAD,
            "material_authors": ["implementer-example"],
        }

    def common(self, stack: ExitStack, state: dict, run_side_effect=None) -> None:
        config = {
            "project": {"repository": "owner/repo", "default_branch": "main"},
            "autonomy": {"level": "L2"},
            "safety": {"emergency_stop": False},
        }
        governance = {
            "control_plane": {
                "fail_closed_if_diff_unavailable": True,
                "human_merge_required": False,
                "protected_paths": [],
                "always_human_paths": [],
            }
        }
        base_context = {
            "config": config,
            "governance": governance,
            "ledger": {"enabled": False},
            "queue": self.queue(),
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
            run_side_effect = lambda command, cwd=None: subprocess.CompletedProcess(
                command, 0, stdout="", stderr=""
            )

        stack.enter_context(patch.object(merge, "emergency_stop_active", return_value=False))
        stack.enter_context(patch.object(merge, "command_exists", return_value=True))
        stack.enter_context(patch.object(merge, "run", side_effect=run_side_effect))
        stack.enter_context(patch.object(merge, "load_json", side_effect=fake_load))
        stack.enter_context(
            patch.object(
                merge,
                "_base_control_context",
                return_value=(base_context, []),
            )
        )
        stack.enter_context(
            patch.object(merge, "_automation_policy_drift_errors", return_value=[])
        )
        stack.enter_context(
            patch.object(merge, "github_repo_from_remote", return_value="owner/repo")
        )
        stack.enter_context(
            patch.object(
                merge,
                "protected_default_branch_context",
                return_value=(
                    {"default_branch": "main", "tip": "c" * 40, "trusted_ref": BASE},
                    [],
                ),
            )
        )
        stack.enter_context(
            patch.object(
                merge,
                "_platform_authors",
                return_value=({"implementer-example"}, []),
            )
        )
        stack.enter_context(
            patch.object(merge, "changed_files", return_value=(["src/change.py"], None))
        )
        stack.enter_context(patch.object(merge, "ledger_enabled", return_value=False))
        stack.enter_context(patch.object(merge, "scope_errors", return_value=[]))
        stack.enter_context(patch.object(merge, "live_pr", return_value=(self.live(), None)))
        stack.enter_context(
            patch.object(merge, "evaluate_required_checks", return_value=(True, [], []))
        )
        stack.enter_context(
            patch.object(merge, "coordination_view", return_value=self.coordination())
        )
        stack.enter_context(
            patch.object(
                merge,
                "_final_coordination_check",
                return_value=([self.active_lease()], []),
            )
        )
        stack.enter_context(
            patch.object(
                merge,
                "append_coordination_event",
                return_value={"event_id": "event-test"},
            )
        )
        stack.enter_context(patch.object(merge, "save_json"))
        stack.enter_context(
            patch.object(
                merge,
                "_verify_reviewer",
                return_value=(
                    {
                        "actor_id": "codex",
                        "login": "review-bot",
                        "authorities": ["code_review"],
                    },
                    [],
                ),
            )
        )
        stack.enter_context(
            patch.object(
                merge,
                "authorize_current_principal",
                return_value=(
                    {
                        "actor_id": "human-owner",
                        "login": "Owner",
                        "authorities": ["merge_execution", "protected_merge", "root"],
                        "policy_provenance": {"source": "base"},
                    },
                    [],
                ),
            )
        )

    def test_merge_refuses_without_assurance_packet(self):
        state = self.state()
        with ExitStack() as stack:
            self.common(stack, state)
            run_mock = merge.run
            stack.enter_context(
                patch.object(sys, "argv", ["merge.py", "--actor", "Owner", "--pr", "1"])
            )
            result = merge.main()
        self.assertEqual(result, 2)
        self.assertEqual(run_mock.call_count, 1)

    def test_spoofed_human_owner_label_cannot_replace_authenticated_principal(self):
        state = self.state()
        with ExitStack() as stack:
            self.common(stack, state)
            stack.enter_context(
                patch.object(
                    merge,
                    "authorize_current_principal",
                    return_value=(
                        {
                            "actor_id": "worker",
                            "login": "worker-login",
                            "authorities": ["merge_execution"],
                            "policy_provenance": {"source": "base"},
                        },
                        [],
                    ),
                )
            )
            stack.enter_context(
                patch.object(
                    sys,
                    "argv",
                    ["merge.py", "--actor", "human-owner", "--pr", "1"],
                )
            )
            result = merge.main()
        self.assertEqual(result, 2)

    def test_unverified_gate_reviewer_blocks_merge(self):
        state = self.state()
        with ExitStack() as stack:
            self.common(stack, state)
            stack.enter_context(
                patch.object(merge, "_verify_reviewer", return_value=(None, ["stale review"]))
            )
            stack.enter_context(patch.object(sys, "argv", ["merge.py", "--pr", "1"]))
            result = merge.main()
        self.assertEqual(result, 2)

    def test_candidate_policy_drift_blocks_automated_merge(self):
        state = self.state()
        with ExitStack() as stack:
            self.common(stack, state)
            stack.enter_context(
                patch.object(
                    merge,
                    "_automation_policy_drift_errors",
                    return_value=["candidate changes .onecompany/ledger.json"],
                )
            )
            stack.enter_context(patch.object(sys, "argv", ["merge.py", "--pr", "1"]))
            result = merge.main()
        self.assertEqual(result, 2)

    def test_unverified_assurance_refuses_before_merge_mutation(self):
        state = self.state()
        with ExitStack() as stack:
            self.common(stack, state)
            run_mock = merge.run
            stack.enter_context(
                patch.object(
                    merge,
                    "_load_assurance_packet",
                    return_value=(self.packet(), "packet.json", None),
                )
            )
            stack.enter_context(patch.object(merge, "validate_structure", return_value=([], [])))
            stack.enter_context(
                patch.object(
                    merge,
                    "verify_trusted_packet",
                    return_value=({"verdict": "UNVERIFIED"}, ["artifact failed"]),
                )
            )
            stack.enter_context(
                patch.object(
                    sys,
                    "argv",
                    [
                        "merge.py",
                        "--actor",
                        "Owner",
                        "--pr",
                        "1",
                        "--assurance-packet",
                        "packet.json",
                    ],
                )
            )
            result = merge.main()
        self.assertEqual(result, 2)
        self.assertEqual(run_mock.call_count, 1)

    def test_pass_attestation_allows_exact_head_merge_with_platform_principal(self):
        state = self.state()

        def fake_run(command, cwd=None):
            if command[:3] == ["gh", "auth", "status"]:
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
            if command[:4] == ["gh", "api", "--method", "PUT"]:
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=json.dumps({"merged": True, "sha": "c" * 40}),
                    stderr="",
                )
            raise AssertionError(f"unexpected command: {command}")

        attestation = {
            "verdict": "PASS",
            "policy_revision": "quality:q;required-checks:r;identity:i",
            "head_sha": HEAD,
            "base_sha": BASE,
            "review": {"review_id": 42, "reviewer_login": "review-bot"},
        }
        with ExitStack() as stack:
            self.common(stack, state, run_side_effect=fake_run)
            run_mock = merge.run
            stack.enter_context(
                patch.object(
                    merge,
                    "_load_assurance_packet",
                    return_value=(self.packet(), "packet.json", None),
                )
            )
            stack.enter_context(patch.object(merge, "validate_structure", return_value=([], [])))
            stack.enter_context(
                patch.object(merge, "verify_trusted_packet", return_value=(attestation, []))
            )
            stack.enter_context(
                patch.object(
                    sys,
                    "argv",
                    [
                        "merge.py",
                        "--actor",
                        "Owner",
                        "--pr",
                        "1",
                        "--assurance-packet",
                        "packet.json",
                    ],
                )
            )
            result = merge.main()
        self.assertEqual(result, 0)
        self.assertEqual(run_mock.call_count, 2)
        self.assertEqual(state["last_merge"]["approved_head"], HEAD)
        self.assertEqual(state["last_merge"]["approved_base"], BASE)
        self.assertEqual(state["last_merge"]["actor"], "human-owner")
        self.assertEqual(state["last_merge"]["platform_login"], "Owner")
        self.assertEqual(len(state["last_merge"]["assurance_attestation_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
