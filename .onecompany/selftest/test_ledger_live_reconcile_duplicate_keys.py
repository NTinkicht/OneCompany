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

import ledger  # noqa: E402
import live_reconcile_run  # noqa: E402


def _inputs(extra: str = "") -> str:
    base = {key: [] for key in live_reconcile_run.KEYS}
    base["main_sha"] = "a" * 40
    text = json.dumps(base)
    return text[:-1] + extra + "}" if extra else text


class DuplicateKeyRefusalTests(unittest.TestCase):
    def test_reject_duplicate_keys_hook_refuses_nested_repeats(self):
        for text in ('{"a": 1, "a": 2}', '{"o": {"x": 1, "x": 2}}', '{"l": [{"y": 1, "y": 1}]}'):
            with self.assertRaisesRegex(ValueError, "duplicate key"):
                json.loads(text, object_pairs_hook=ledger.reject_duplicate_keys)
        self.assertEqual(json.loads('{"a": {"b": 1}}', object_pairs_hook=ledger.reject_duplicate_keys), {"a": {"b": 1}})

    def test_ledger_post_refuses_duplicate_payload_keys_before_posting(self):
        argv = ["ledger.py", "post", "--type", "COMMENT", "--payload-json", '{"head": "a", "head": "b"}']
        out = io.StringIO()
        with mock.patch.object(sys, "argv", argv), mock.patch.object(ledger, "post_event") as post, \
                contextlib.redirect_stdout(out):
            code = ledger.main()
        self.assertEqual(code, 2)
        self.assertIn("duplicate key", out.getvalue())
        post.assert_not_called()

    def test_ledger_post_positive_control_parses_unique_keys(self):
        argv = ["ledger.py", "post", "--type", "COMMENT", "--payload-json", '{"head": "a"}']
        out = io.StringIO()
        with mock.patch.object(sys, "argv", argv), mock.patch.object(ledger, "post_event", return_value={"ok": 1}), \
                contextlib.redirect_stdout(out):
            ledger.main()
        self.assertNotIn("duplicate key", out.getvalue())

    def test_live_reconcile_inputs_refuse_duplicate_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "inputs.json"
            path.write_text(_inputs(), encoding="utf-8")
            self.assertEqual(live_reconcile_run.load_inputs(path)["main_sha"], "a" * 40)
            path.write_text(_inputs(', "main_sha": "' + "b" * 40 + '"'), encoding="utf-8")
            with self.assertRaises(ValueError):
                live_reconcile_run.load_inputs(path)


if __name__ == "__main__":
    unittest.main()
