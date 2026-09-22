"""Regression for the OneCompany source-only real local demo command."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "onecompany.py"
DEMO = ROOT / "scripts" / "phase1_vertical_smoke.py"
AVAILABLE = ENTRY.is_file() and DEMO.is_file()


@unittest.skipUnless(AVAILABLE, "source-only local demo helper not installed in target")
class DemoCommandTests(unittest.TestCase):
    def test_real_demo_help_routes_to_existing_helper(self):
        completed = subprocess.run(
            [sys.executable, str(ENTRY), "demo", "--help"],
            cwd=ROOT, capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        for flag in ("--target", "--repository", "--brief", "--head", "--base"):
            self.assertIn(flag, completed.stdout)

    def test_missing_owner_inputs_fail_closed_without_starting_app(self):
        completed = subprocess.run(
            [sys.executable, str(ENTRY), "demo"],
            cwd=ROOT, capture_output=True, text=True, timeout=15,
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("--target", completed.stderr)
        self.assertIn("--brief", completed.stderr)

    def test_wrapper_preserves_args_and_child_exit_status(self):
        spec = importlib.util.spec_from_file_location("onecompany_demo_entrypoint", ENTRY)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with mock.patch.object(sys, "argv", ["onecompany.py", "demo", "--target", "/tmp/example"]), \
             mock.patch.object(module.subprocess, "run", return_value=mock.Mock(returncode=17)) as run:
            self.assertEqual(module.main(), 17)
        args = run.call_args.args[0]
        self.assertEqual(args[:2], [sys.executable, str(DEMO)])
        self.assertEqual(args[2:], ["--target", "/tmp/example"])
        self.assertEqual(run.call_args.kwargs["cwd"], str(ROOT))
        self.assertIs(run.call_args.kwargs["check"], False)


if __name__ == "__main__":
    unittest.main()
