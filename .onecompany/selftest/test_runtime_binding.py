"""Runtime binding (OC-P0-14 first slice): real ephemeral loopback port, fail-closed projection."""
from __future__ import annotations

import copy
import importlib.util
import socket
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MOD_PATH = ROOT / "scripts" / "runtime_binding.py"
APP_PATH = ROOT / "examples" / "vertical-slice" / "app.py"
if MOD_PATH.is_file() and APP_PATH.is_file():
    SPEC = importlib.util.spec_from_file_location("runtime_binding", MOD_PATH)
    rb = importlib.util.module_from_spec(SPEC)
    sys.modules[SPEC.name] = rb
    SPEC.loader.exec_module(rb)

HEAD = "a" * 40
BASE = "b" * 40


@unittest.skipUnless(APP_PATH.is_file(), "source-only disposable demo not installed")
class RuntimeBindingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.ws = cls._tmp.name
        cls.manifest = rb.capture("WU-P1-RUNTIME-BINDING-001", "run/1", cls.ws, HEAD, BASE)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def args(self, **over):
        base = dict(wu_id="WU-P1-RUNTIME-BINDING-001", run_key="run/1", workspace=self.ws,
                    head_sha=HEAD, base_sha=BASE)
        base.update(over)
        return base

    def test_capture_records_real_evidence_and_clean_stop(self) -> None:
        m = self.manifest
        self.assertEqual(m["health"]["status"], 200)
        self.assertTrue(m["crud_round_trip"]["ok"])
        self.assertTrue(m["cleanup"]["ok"])
        self.assertFalse(m["production_qualified"])
        self.assertTrue(m["build_digest"].startswith("sha256:"))
        self.assertEqual(m["head_sha"], HEAD)
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", m["port"]), timeout=1)
        self.assertEqual(rb.verify(m, **self.args()), [])

    def test_mismatches_are_refused(self) -> None:
        for key, bad in (("wu_id", "WU-OTHER"), ("run_key", "run/2"), ("head_sha", "c" * 40),
                         ("base_sha", "c" * 40)):
            with self.subTest(key=key):
                self.assertIn(f"{key} mismatch", rb.verify(self.manifest, **self.args(**{key: bad})))
        with tempfile.TemporaryDirectory() as other:
            self.assertIn("workspace mismatch", rb.verify(self.manifest, **self.args(workspace=other)))

    def test_missing_or_tampered_fields_are_refused(self) -> None:
        for field in rb.REQUIRED:
            m = copy.deepcopy(self.manifest)
            m.pop(field)
            with self.subTest(field=field):
                self.assertTrue(rb.verify(m, **self.args()))
        m = copy.deepcopy(self.manifest)
        m["build_digest"] = "sha256:" + "0" * 64
        self.assertIn("build_digest mismatch", rb.verify(m, **self.args()))
        m = copy.deepcopy(self.manifest)
        m["production_qualified"] = True
        self.assertTrue(rb.verify(m, **self.args()))
        m = copy.deepcopy(self.manifest)
        m["crud_round_trip"]["ok"] = False
        self.assertIn("CRUD round trip failed", rb.verify(m, **self.args()))
        m = copy.deepcopy(self.manifest)
        m["cleanup"]["ok"] = False
        self.assertIn("cleanup not verified", rb.verify(m, **self.args()))
        self.assertTrue(rb.verify("not-a-dict", **self.args()))

    def test_projection_is_ready_only_with_exact_head_ci_and_tests(self) -> None:
        kw = dict(wu_id="WU-P1-RUNTIME-BINDING-001", run_key="run/1", workspace=self.ws,
                  current_head_sha=HEAD, current_base_sha=BASE)
        ok = rb.project(self.manifest, ci_state="success", tests_passed=True, **kw)
        self.assertEqual(ok["state"], "ready_to_preview")
        self.assertFalse(ok["production_qualified"])
        self.assertIn("not production-qualified", ok["label"])
        for ci, tests in ((None, True), ("failure", True), ("success", False), ("success", None)):
            with self.subTest(ci=ci, tests=tests):
                self.assertEqual(rb.project(self.manifest, ci_state=ci, tests_passed=tests, **kw)["state"], "blocked")
        moved = dict(kw, current_head_sha="d" * 40)
        self.assertEqual(rb.project(self.manifest, ci_state="success", tests_passed=True, **moved)["state"], "blocked")

    def test_bad_inputs_refused_before_starting_anything(self) -> None:
        for over in ({"wu_id": ""}, {"run_key": "bad key"}, {"head_sha": "abc"}, {"base_sha": "G" * 40},
                     {"workspace": "/nonexistent-dir-xyz"}):
            with self.subTest(over=over):
                with self.assertRaises(rb.BindingError):
                    rb.capture(**{**self.args(), **over})

    def test_cli_exit_codes(self) -> None:
        argv = ["--wu", "W1", "--run-key", "r1", "--workspace", self.ws, "--head", HEAD, "--base", BASE]
        self.assertEqual(rb.main(argv + ["--ci", "success", "--tests", "passed"]), 0)
        self.assertEqual(rb.main(argv), 1)
        self.assertEqual(rb.main(["--wu", "W1", "--run-key", "r1", "--head", "x", "--base", BASE]), 2)


if __name__ == "__main__":
    unittest.main()
