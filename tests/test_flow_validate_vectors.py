"""OC-P0-03 vectors for flow_validate: global WIP, per-actor capacity, no-idle fault.

Each test copies the real control-plane documents into a temporary directory,
applies one mutation and asserts the exact validator message.
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

import flow_validate  # noqa: E402
from capacity_lib import implementation_capacity_limit  # noqa: E402

DOCUMENTS = ("config.json", "planning.json", "queue.json", "state.json", "actors.json",
             "readiness.json", "budget.json", "dispatch.json")


def lease(n, actor="chatgpt", status="active", role="implementation"):
    return {"id": f"L{n}", "actor": actor, "work_unit": f"WU-X-{n}", "status": status, "role": role}


class FlowValidateVectors(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.control = Path(tmp.name)
        for name in DOCUMENTS:
            shutil.copy(ROOT / ".onecompany" / name, self.control / name)
        patcher = mock.patch.object(flow_validate, "CONTROL", self.control)
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
            code = flow_validate.main()
        return code, out.getvalue()

    def set_global_limit(self, n):
        self.edit("planning.json", lambda d: d["parallel_execution"].__setitem__(
            "max_concurrent_implementation_streams", n))

    def set_leases(self, leases):
        self.edit("state.json", lambda d: d.__setitem__("active_leases", leases))

    def test_repository_control_plane_passes(self):
        code, output = self.run_validator()
        self.assertEqual(code, 0, output)
        self.assertIn("Flow validation PASS", output)

    def test_active_streams_above_global_wip_limit_fail(self):
        self.set_global_limit(1)
        self.set_leases([lease(1, "human-owner"), lease(2, "claude")])
        code, output = self.run_validator()
        self.assertEqual(code, 1, output)
        self.assertIn("ERROR: active implementation streams 2 exceed global WIP limit 1", output)

    def test_non_implementation_and_inactive_leases_do_not_count_toward_wip(self):
        self.set_global_limit(1)
        self.set_leases([lease(1, "chatgpt"), lease(2, "claude", role="review"),
                         lease(3, "claude", status="released")])
        code, output = self.run_validator()
        self.assertEqual(code, 0, output)
        self.assertNotIn("exceed global WIP limit", output)

    def test_actor_above_verified_capacity_fails_even_within_global_limit(self):
        readiness = json.loads((self.control / "readiness.json").read_text(encoding="utf-8"))
        ready = {a["actor_id"]: a for a in readiness["actors"]}
        limit = implementation_capacity_limit(ready["human-owner"])
        self.assertEqual(limit, 0, "fixture assumption: human-owner has no implementation capacity")
        self.set_global_limit(4)
        self.set_leases([lease(1, "human-owner")])
        code, output = self.run_validator()
        self.assertEqual(code, 1, output)
        self.assertIn(f"ERROR: actor human-owner has 1 implementation streams above verified capacity {limit}", output)
        self.assertNotIn("exceed global WIP limit", output)

    def test_unknown_actor_has_zero_capacity(self):
        self.set_leases([lease(1, "ghost-actor")])
        code, output = self.run_validator()
        self.assertEqual(code, 1, output)
        self.assertIn("actor ghost-actor has 1 implementation streams above verified capacity 0", output)

    def test_idle_with_dispatchable_ready_work_is_a_fault_at_l4(self):
        pool = {"free_slots": 1, "actors": [{"actor": "codex", "free_slots": 1}], "rejected": []}
        with mock.patch.object(flow_validate, "implementation_pool", return_value=pool):
            code, output = self.run_validator()
        self.assertEqual(code, 1, output)
        self.assertIn("ERROR: FAULT_IDLE_WITH_READY_WORK:", output)
        self.assertIn("WU-CLOUD-MISTRAL-DEV-001", output)

    def test_idle_fault_not_raised_when_no_idle_disabled(self):
        self.edit("config.json", lambda d: d["no_idle"].__setitem__("enabled", False))
        pool = {"free_slots": 1, "actors": [{"actor": "codex", "free_slots": 1}], "rejected": []}
        with mock.patch.object(flow_validate, "implementation_pool", return_value=pool):
            code, output = self.run_validator()
        self.assertEqual(code, 0, output)
        self.assertNotIn("FAULT_IDLE_WITH_READY_WORK", output)

    def test_ready_work_without_unattended_capacity_warns_not_faults(self):
        code, output = self.run_validator()
        self.assertEqual(code, 0, output)
        self.assertIn("WARN: CAPACITY_BLOCKED:", output)

    def test_stale_safe_start_cache_warns(self):
        self.edit("state.json", lambda d: d.__setitem__("safe_start_candidates", ["WU-STALE-001"]))
        code, output = self.run_validator()
        self.assertEqual(code, 0, output)
        self.assertIn("state.safe_start_candidates differs", output)


if __name__ == "__main__":
    unittest.main()
