from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import handoff  # noqa: E402
import handoff_runtime  # noqa: E402
import l5_trust_boundary as tb  # noqa: E402


class DuplicateKeyRefusalTests(unittest.TestCase):
    def test_handoff_main_refuses_duplicate_keys_in_hint_and_snapshot(self):
        for hint, snapshot in (
            ('{"kind": "A", "kind": "B"}', "{}"),
            ("{}", '{"head": "a", "nested": {"x": 1, "x": 2}}'),
        ):
            argv = ["handoff.py", "--hint-json", hint, "--authoritative-json", snapshot]
            err = io.StringIO()
            with mock.patch.object(sys, "argv", argv), contextlib.redirect_stderr(err):
                self.assertEqual(handoff.main(), 2)
            self.assertIn("duplicate key", err.getvalue())

    def test_handoff_main_still_parses_unique_keys(self):
        argv = ["handoff.py", "--hint-json", "{not json", "--authoritative-json", "{}"]
        err = io.StringIO()
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stderr(err):
            self.assertEqual(handoff.main(), 2)
        self.assertNotIn("duplicate key", err.getvalue())

    def test_load_event_refuses_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "event.json"
            path.write_text('{"action": "closed", "action": "opened"}', encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "duplicate key"):
                handoff_runtime.load_event(str(path))
            path.write_text('{"action": "opened"}', encoding="utf-8")
            self.assertEqual(handoff_runtime.load_event(str(path)), {"action": "opened"})

    def test_trust_policy_with_duplicate_keys_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "trust-policy.json"
            if tb.POLICY_PATH.exists():
                self.assertIsNotNone(tb.load_trust_policy(tb.POLICY_PATH))
            path.write_text('{"a": ["x"], "a": ["y"]}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "TRUST_POLICY_DUPLICATE_KEY"):
                tb.load_trust_policy(path)
            path.write_text('{"outer": {"a": 1, "a": 2}}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "TRUST_POLICY_DUPLICATE_KEY"):
                tb.load_trust_policy(path)


if __name__ == "__main__":
    unittest.main()
