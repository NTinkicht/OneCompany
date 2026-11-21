"""OC-P0-10 vectors for handoff_validate: the B2 event-driven handoff boundary.

Each test copies the real control-plane documents into a temporary directory,
applies one mutation and asserts the exact validator message, so every refusal
is shown to fire for the reason under test (the unmutated repository passes).
"""
import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import handoff  # noqa: E402
import handoff_validate  # noqa: E402

DOCUMENTS = ("config.json", "supervision.json", "handoffs.json")


class HandoffValidateVectors(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.control = Path(tmp.name)
        for name in DOCUMENTS:
            shutil.copy(ROOT / ".onecompany" / name, self.control / name)
        for target, attr, value in (
            (handoff_validate, "CONTROL", self.control),
            (handoff, "CONFIG_PATH", self.control / "handoffs.json"),
        ):
            patcher = mock.patch.object(target, attr, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def edit(self, name, mutate):
        path = self.control / name
        data = json.loads(path.read_text(encoding="utf-8"))
        mutate(data)
        path.write_text(json.dumps(data), encoding="utf-8")

    def run_validator(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = handoff_validate.main()
        return code, out.getvalue()

    def assert_refused(self, message):
        code, output = self.run_validator()
        self.assertEqual(code, 1, output)
        self.assertIn("B2 handoff validation FAIL", output)
        self.assertIn(f"- {message}", output)
        return output

    def test_repository_control_plane_passes(self):
        code, output = self.run_validator()
        self.assertEqual(code, 0, output)
        self.assertIn("B2 handoff validation PASS", output)

    def test_every_safety_invariant_is_enforced(self):
        keys = json.loads((self.control / "handoffs.json").read_text())["safety"]
        self.assertGreaterEqual(len(keys), 10)
        for key in (
            "events_are_wake_hints_only", "must_reconcile_authoritative_state",
            "hint_payload_can_create_authority", "proposal_only_until_activation",
            "never_create_duplicate_writer", "emergency_stop_is_sovereign",
            "human_code_owner_remains_human", "zero_extra_spend_required",
            "pull_request_target_forbidden", "candidate_cache_is_authority",
        ):
            with self.subTest(key=key):
                original = (self.control / "handoffs.json").read_text()
                self.edit("handoffs.json", lambda d, k=key: d["safety"].__setitem__(k, not d["safety"][k]))
                self.assert_refused(f"handoff safety invariant mismatch:{key}")
                (self.control / "handoffs.json").write_text(original)

    def test_disabled_and_non_active_policy_refused(self):
        self.edit("handoffs.json", lambda d: d.__setitem__("enabled", False))
        self.assert_refused("B2 handoffs must be enabled")
        self.edit("handoffs.json", lambda d: (d.__setitem__("enabled", True), d.__setitem__("mode", "proposal")))
        self.assert_refused("B2 handoff mode must be active")

    def test_missing_activation_proof_refused(self):
        self.edit("handoffs.json", lambda d: d["activation"].__setitem__("b1_protected_main_proven", False))
        output = self.assert_refused("B1 protected-main proof is required")
        self.assertIn("- active B2 policy is not activation-ready", output)

    def test_missing_ledger_replay_proof_refused(self):
        self.edit("handoffs.json", lambda d: d["activation"].__setitem__("ledger_replay_proven", False))
        self.assert_refused("protected-main ledger replay proof is required")

    def test_too_few_evidence_refs_refused(self):
        self.edit("handoffs.json", lambda d: d["activation"].__setitem__("evidence_refs", ["only-one"]))
        self.assert_refused("activation requires protected-main and workflow evidence refs")

    def test_publisher_identity_and_event_type_both_required(self):
        self.edit("handoffs.json", lambda d: d["publisher_policy"].__setitem__(
            "publisher_identity_and_event_type_both_required", False))
        self.assert_refused("publisher identity and event type must both be enforced")

    def test_publisher_mapping_shape_refused(self):
        self.edit("handoffs.json", lambda d: d["publisher_policy"].__setitem__("automation_publishers", []))
        self.assert_refused("automation_publishers must be an object")
        self.edit("handoffs.json", lambda d: d["publisher_policy"].__setitem__(
            "automation_publishers", {"bot[bot]": []}))
        self.assert_refused("every trusted automation publisher requires scoped event types")

    def test_github_actions_mutation_refused(self):
        self.edit("handoffs.json", lambda d: d["runtime"].__setitem__("github_actions_mutation_allowed", True))
        self.assert_refused("handoff runtime invariant mismatch:github_actions_mutation_allowed")

    def test_automatic_merge_requires_scheduled_mutation_authority(self):
        # With scheduled mutation authority withdrawn, automatic merge must be refused.
        self.edit("supervision.json", lambda d: d["chatgpt_tasks"].__setitem__("may_mutate", False))
        output = self.assert_refused("handoff runtime invariant mismatch:automatic_merge_allowed")
        self.assertIn("handoff runtime invariant mismatch:scheduled_chatgpt_mutation_allowed", output)
        self.assertIn("handoff runtime invariant mismatch:automatic_failover_allowed", output)

    def test_autonomy_level_mismatch_refused(self):
        self.edit("config.json", lambda d: d["autonomy"].__setitem__("level", "L2"))
        self.assert_refused("handoff runtime invariant mismatch:current_autonomy_level")

    def test_l1_fails_closed_against_l4_runtime_shape(self):
        self.edit("config.json", lambda d: d["autonomy"].__setitem__("level", "L1"))
        output = self.assert_refused("handoff runtime invariant mismatch:current_autonomy_level")
        self.assertIn("handoff runtime invariant mismatch:scheduled_chatgpt_mutation_allowed", output)

    def test_malformed_autonomy_level_fails_closed(self):
        self.edit("config.json", lambda d: d["autonomy"].__setitem__("level", "high"))
        code, output = self.run_validator()
        self.assertEqual(code, 1, output)
        self.assertIn("B2 handoff validation FAIL: invalid autonomy level: high", output)

    def test_non_object_policy_fails_closed(self):
        (self.control / "handoffs.json").write_text("[]", encoding="utf-8")
        code, output = self.run_validator()
        self.assertEqual(code, 1, output)
        self.assertIn("handoff policy must be an object", output)

    def test_missing_policy_file_fails_closed(self):
        (self.control / "handoffs.json").unlink()
        code, output = self.run_validator()
        self.assertEqual(code, 1, output)
        self.assertIn("B2 handoff validation FAIL", output)


if __name__ == "__main__":
    unittest.main()
