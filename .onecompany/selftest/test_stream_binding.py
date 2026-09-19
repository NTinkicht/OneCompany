from __future__ import annotations

import argparse
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import lease_core
from stream_binding import binding_violations, duplicate_queue_binding_violations


class CanonicalStreamBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.queue = {
            "WU-A": {"id": "WU-A", "branch": "wu-a", "pr": 12, "status": "READY"},
            "WU-B": {"id": "WU-B", "branch": "wu-b", "pr": 13, "status": "READY"},
        }

    def test_correct_existing_binding_passes_when_not_actively_leased(self) -> None:
        self.assertEqual(
            binding_violations("WU-A", "wu-a", 12, self.queue, []), []
        )

    def test_new_pr_and_branch_cannot_steal_existing_work_unit(self) -> None:
        problems = binding_violations("WU-A", "wu-a-copy", 99, self.queue, [])
        self.assertTrue(any(x.startswith("canonical_branch_mismatch:") for x in problems))
        self.assertTrue(any(x.startswith("canonical_pr_mismatch:") for x in problems))

    def test_other_work_units_branch_and_pr_cannot_be_reused(self) -> None:
        self.queue["WU-C"] = {"id": "WU-C", "branch": None, "pr": None}
        problems = binding_violations("WU-C", "wu-b", 12, self.queue, [])
        self.assertIn("branch_owned_by_other_wu:WU-B", problems)
        self.assertIn("pr_owned_by_other_wu:WU-A", problems)

    def test_active_canonical_lease_returns_existing_stream_identity(self) -> None:
        active = [{
            "id": "lease-winner", "role": "implementation",
            "work_unit": "WU-A", "branch": "wu-a", "pr": 12,
        }]
        problems = binding_violations("WU-A", "wu-a", 12, self.queue, active)
        self.assertEqual(len(problems), 1)
        self.assertIn("lease=lease-winner", problems[0])
        self.assertIn("branch=wu-a:pr=12", problems[0])

    def test_queue_validator_rejects_two_wus_claiming_one_pr_or_branch(self) -> None:
        queue = [
            {"id": "WU-A", "branch": "shared", "pr": 42},
            {"id": "WU-B", "branch": "shared", "pr": 42},
        ]
        problems = duplicate_queue_binding_violations(queue)
        self.assertEqual(len(problems), 2)
        self.assertTrue(any("canonical PR #42" in x for x in problems))
        self.assertTrue(any("canonical branch 'shared'" in x for x in problems))

    def test_queue_validator_accepts_independent_wu_streams(self) -> None:
        self.assertEqual(
            duplicate_queue_binding_violations(list(self.queue.values())), []
        )

    def test_durable_binding_requires_explicit_branch_and_pr(self) -> None:
        queue = {"WU-A": {"id": "WU-A", "branch": None, "pr": 12}}
        errors = binding_violations(
            "WU-A", "chosen-at-runtime", 12, queue, [],
            require_complete=True,
        )
        self.assertIn("canonical_branch_missing:WU-A", errors)
        queue["WU-A"]["branch"] = "canonical"
        queue["WU-A"]["pr"] = None
        errors = binding_violations(
            "WU-A", "canonical", 12, queue, [],
            require_complete=True,
        )
        self.assertIn("canonical_pr_missing:WU-A", errors)

    def test_local_acquire_rejects_stream_drift_without_appending_event(self) -> None:
        import lease
        candidate = {
            "id": "WU-A", "branch": "wu-a", "pr": 12,
            "status": "READY", "dependencies": [],
        }
        queue = {"work_units": [candidate]}
        state = {"active_leases": [], "active_streams": []}
        args = argparse.Namespace(
            wu="WU-A", actor="builder", branch="other-branch", pr=12,
            start_head="a" * 40,
        )
        def local_doc(path: Path):
            return {
                "queue.json": queue,
                "planning.json": {"parallel_execution": {}},
                "state.json": state,
            }[Path(path).name]
        with (
            patch.object(lease, "emergency_stop_active", return_value=False),
            patch.object(lease, "load_json", side_effect=local_doc),
            patch.object(lease, "_active_view", return_value=({}, [])),
            patch.object(lease, "append_local_event") as event,
            patch.object(lease, "save_json") as save,
        ):
            result = lease._local_acquire(args)
        self.assertEqual(result, 2)
        event.assert_not_called()
        save.assert_not_called()

    def test_unknown_or_incomplete_binding_fails_closed(self) -> None:
        self.assertIn(
            "unknown_work_unit:WU-MISSING",
            binding_violations("WU-MISSING", "wu-new", 14, self.queue, []),
        )
        self.assertIn(
            "invalid_implementation_pr",
            binding_violations("WU-A", "wu-a", True, self.queue, []),
        )

    def test_acquire_rejects_active_same_wu_before_writing_ledger(self) -> None:
        state = {"active_leases": [], "active_streams": []}
        queue = {"work_units": [self.queue["WU-A"], self.queue["WU-B"]]}
        active = [{
            "id": "lease-winner", "role": "implementation",
            "work_unit": "WU-A", "branch": "wu-a", "pr": 12,
        }]
        args = argparse.Namespace(
            wu="WU-A", actor="builder", branch="wu-a-copy",
            pr=15, start_head="a" * 40,
        )
        def local_doc(path: Path):
            name = Path(path).name
            return {
                "state.json": state,
                "queue.json": queue,
                "planning.json": {"parallel_execution": {}},
            }[name]

        with (
            patch.object(lease_core, "emergency_stop_active", return_value=False),
            patch.object(lease_core, "load_json", side_effect=local_doc),
            patch.object(lease_core, "ledger_enabled", return_value=True),
            patch.object(lease_core, "authoritative", return_value=(active, [])),
            patch.object(lease_core, "trusted_pr_base") as base,
            patch.object(lease_core, "post_event") as post,
            patch.object(lease_core, "save_json") as save,
        ):
            result = lease_core.acquire(args)
        self.assertEqual(result, 2)
        base.assert_not_called()
        post.assert_not_called()
        save.assert_not_called()

    def test_trusted_base_branch_drift_prevents_ledger_append(self) -> None:
        state = {"active_leases": [], "active_streams": []}
        local_queue = {"work_units": [{"id": "WU-A", "status": "READY"}]}
        trusted_item = {"id": "WU-A", "status": "READY", "branch": "canonical", "pr": 12}
        args = argparse.Namespace(
            wu="WU-A", actor="builder", branch="unexpected",
            pr=12, start_head="a" * 40,
        )
        def local_doc(path: Path):
            return {
                "state.json": state,
                "queue.json": local_queue,
                "planning.json": {"parallel_execution": {}},
            }[Path(path).name]
        context = {
            "work_item": trusted_item, "work_map": {"WU-A": trusted_item},
            "planning": {"parallel_execution": {}},
            "policy_blobs": {}, "actor_limit": 1, "actor_eligible": True,
        }
        with (
            patch.object(lease_core, "emergency_stop_active", return_value=False),
            patch.object(lease_core, "load_json", side_effect=local_doc),
            patch.object(lease_core, "ledger_enabled", return_value=True),
            patch.object(lease_core, "authoritative", return_value=([], [])),
            patch.object(lease_core, "list_events", return_value=[]),
            patch.object(lease_core, "derive", return_value={"verified_merged_work_units": []}),
            patch.object(lease_core, "trusted_pr_base", return_value="b" * 40),
            patch.object(
                lease_core, "trusted_admission_context", return_value=(context, None)
            ),
            patch.object(lease_core, "post_event") as post,
            patch.object(lease_core, "save_json") as save,
        ):
            result = lease_core.acquire(args)
        self.assertEqual(result, 2)
        post.assert_not_called()
        save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
