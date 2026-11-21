"""OC-P0-03 / OC-P0-04 vectors for queue_validate WIP-limit and active-WU conflict rules.

Each test copies the real control-plane documents into a temporary directory,
applies one mutation and asserts the exact validator message, so the WIP and
overlapping-scope refusals cannot silently regress (and disjoint work is not
over-refused).
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

import queue_validate  # noqa: E402

DOCUMENTS = ("planning.json", "queue.json")
A, B = "WU-CLOUD-MISTRAL-DEV-001", "WU-MISTRAL-RECOVERY-001"


class QueueActiveVectors(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.control = Path(tmp.name)
        for name in DOCUMENTS:
            shutil.copy(ROOT / ".onecompany" / name, self.control / name)
        patcher = mock.patch.object(queue_validate, "CONTROL", self.control)
        patcher.start()
        self.addCleanup(patcher.stop)

    def edit(self, name, mutate):
        path = self.control / name
        data = json.loads(path.read_text(encoding="utf-8"))
        mutate(data)
        path.write_text(json.dumps(data), encoding="utf-8")

    def wu(self, data, wu_id):
        return next(item for item in data["work_units"] if item["id"] == wu_id)

    def activate(self, *ids, status="IN_PROGRESS", **fields):
        def mutate(data):
            for wu_id in ids:
                item = self.wu(data, wu_id)
                item["status"] = status
                item.update(fields)
        self.edit("queue.json", mutate)

    def run_validator(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = queue_validate.main()
        return code, out.getvalue()

    def test_disjoint_active_work_within_wip_limit_passes(self):
        self.activate(A, B)
        code, output = self.run_validator()
        self.assertEqual(code, 0, output)

    def test_active_work_above_wip_limit_is_rejected(self):
        self.edit("planning.json", lambda d: d["parallel_execution"].__setitem__("max_concurrent_implementation_streams", 1))
        self.activate(A, B)
        code, output = self.run_validator()
        self.assertEqual(code, 1, output)
        self.assertIn("ERROR: queue contains 2 active-like WUs above configured WIP limit 1", output)

    def test_overlapping_write_scope_between_active_work_is_rejected(self):
        self.activate(A, B)
        self.edit("queue.json", lambda d: self.wu(d, B).__setitem__("write_scope", list(self.wu(d, A)["write_scope"])))
        code, output = self.run_validator()
        self.assertEqual(code, 1, output)
        self.assertIn(f"ERROR: active-like WUs {A} and {B} conflict: write_scope_overlap", output)

    def test_overlapping_resource_lock_between_active_work_is_rejected(self):
        self.activate(A, B)
        self.edit("queue.json", lambda d: self.wu(d, B).__setitem__("resource_locks", list(self.wu(d, A)["resource_locks"])))
        code, output = self.run_validator()
        self.assertEqual(code, 1, output)
        self.assertIn(f"ERROR: active-like WUs {A} and {B} conflict: resource_lock_overlap", output)

    def test_serial_policy_active_work_conflicts_with_other_active_work(self):
        self.activate(A, B)
        self.edit("queue.json", lambda d: self.wu(d, A).__setitem__("parallelism", "serial"))
        code, output = self.run_validator()
        self.assertEqual(code, 1, output)
        self.assertIn(f"ERROR: active-like WUs {A} and {B} conflict: serial_policy", output)

    def test_ready_with_unmerged_dependency_warns_without_failing(self):
        self.edit("queue.json", lambda d: self.wu(d, A)["dependencies"].append(B))
        code, output = self.run_validator()
        self.assertEqual(code, 0, output)
        self.assertIn(f"WARN: {A}: READY has dependencies not marked DONE/MERGED: ['{B}']", output)


if __name__ == "__main__":
    unittest.main()
