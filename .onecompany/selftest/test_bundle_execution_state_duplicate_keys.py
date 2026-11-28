"""#638: bundle snapshot and execution state/pending files refuse duplicate JSON keys."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import github_bundle_snapshot  # noqa: E402
from execution_core import ExecutionStore, JournalIntegrityError, RunContext, reject_duplicate_keys  # noqa: E402

WU = "WU-OC-P0-04-DUPKEYS"


class HookTests(unittest.TestCase):
    def test_hooks_refuse_nested_repeats(self):
        for hook in (reject_duplicate_keys, github_bundle_snapshot._reject_duplicate_keys):
            for text in ('{"a": 1, "a": 2}', '{"o": {"x": 1, "x": 2}}', '{"l": [{"y": 1, "y": 1}]}'):
                with self.assertRaisesRegex(ValueError, "duplicate key"):
                    json.loads(text, object_pairs_hook=hook)
            self.assertEqual(json.loads('{"a": {"b": 1}}', object_pairs_hook=hook), {"a": {"b": 1}})


class BundleCliTests(unittest.TestCase):
    def _run(self, text: str) -> tuple[int, str]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bundle.json"
            path.write_text(text, encoding="utf-8")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code = github_bundle_snapshot.main([str(path)])
            return code, err.getvalue()

    def test_duplicate_key_bundle_is_refused_as_unreadable(self):
        code, err = self._run('{"main_sha": "a", "main_sha": "b"}')
        self.assertEqual(code, github_bundle_snapshot.EXIT_INVALID)
        self.assertIn("unreadable or not JSON", err)

    def test_positive_control_unique_keys_reach_bundle_validation(self):
        code, err = self._run('{"main_sha": "a"}')
        self.assertEqual(code, github_bundle_snapshot.EXIT_INVALID)
        self.assertNotIn("unreadable or not JSON", err)


class ExecutionStateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = ExecutionStore(Path(self._tmp.name))
        self.ctx = RunContext.new(WU, "dupkeys", {"AC1": "x"}, run_id="run-dup")
        self.store.persist_event(self.ctx, "created")

    def test_positive_control_loads(self):
        self.assertEqual(self.store.load(WU).key.wu_id, WU)

    def test_duplicate_key_state_file_fails_closed(self):
        path = self.store.state_path(WU)
        text = path.read_text(encoding="utf-8")
        path.write_text(text.rstrip()[:-1] + ', "objective": "forged"}', encoding="utf-8")
        with self.assertRaises(JournalIntegrityError):
            self.store.load(WU)

    def test_duplicate_key_pending_record_fails_closed(self):
        pending = self.store.pending_path(WU)
        pending.write_text('{"operation_id": "a", "operation_id": "b"}', encoding="utf-8")
        with self.assertRaises(JournalIntegrityError):
            self.store.load(WU)


if __name__ == "__main__":
    unittest.main()
