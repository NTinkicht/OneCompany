"""Real source-checkout preview-local entrypoint and actual localhost HTTP smoke."""
import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import unittest
import urllib.request
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "onecompany.py"
APP = ROOT / "examples" / "vertical-slice" / "app.py"
AVAILABLE = ENTRY.is_file() and APP.is_file()


@unittest.skipUnless(AVAILABLE, "source-only disposable app is not installed in target")
class PreviewLocalCommandTests(unittest.TestCase):
    def test_help_and_unknown_argument_refuse(self):
        help_result = subprocess.run(
            [sys.executable, str(ENTRY), "preview-local", "--help"],
            cwd=ROOT, text=True, capture_output=True, timeout=15,
        )
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("--port", help_result.stdout)
        wrong = subprocess.run(
            [sys.executable, str(ENTRY), "preview-local", "--unknown"],
            cwd=ROOT, text=True, capture_output=True, timeout=15,
        )
        self.assertNotEqual(wrong.returncode, 0)
        self.assertIn("--unknown", wrong.stderr)

    def test_routes_to_existing_app_without_another_server(self):
        spec = importlib.util.spec_from_file_location("onecompany_preview_entrypoint", ENTRY)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with mock.patch.object(sys, "argv", ["onecompany.py", "preview-local", "--port", "0"]), \
             mock.patch.object(module.subprocess, "run", return_value=mock.Mock(returncode=3)) as run:
            self.assertEqual(module.main(), 3)
        self.assertEqual(run.call_args.args[0],
                         [sys.executable, str(ROOT / "scripts" / ".." / "examples" / "vertical-slice" / "app.py"), "--port", "0"])
        self.assertIs(run.call_args.kwargs["check"], False)

    @unittest.skipUnless(os.name == "posix", "SIGINT shutdown integration is POSIX-specific")
    def test_real_start_health_page_and_sigint_cleanup(self):
        proc = subprocess.Popen(
            [sys.executable, str(ENTRY), "preview-local", "--port", "0"],
            cwd=ROOT, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            line = proc.stdout.readline()
            self.assertTrue(line.startswith("Local-only fixture: http://127.0.0.1:"),
                            f"unexpected local preview startup: {line!r}")
            url = line.split("Local-only fixture: ", 1)[1].strip()
            self.assertTrue(url.endswith("/"))
            with urllib.request.build_opener(
                urllib.request.ProxyHandler({})
            ).open(url + "health", timeout=3) as response:
                self.assertEqual(response.status, 200)
                self.assertIn("local_disposable", response.read().decode())
            with urllib.request.build_opener(
                urllib.request.ProxyHandler({})
            ).open(url, timeout=3) as response:
                self.assertEqual(response.status, 200)
                self.assertIn("My checklist", response.read().decode())
        finally:
            if proc.poll() is None:
                proc.send_signal(signal.SIGINT)
            try:
                proc.communicate(timeout=6)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate(timeout=3)
            self.assertIsNotNone(proc.returncode)


if __name__ == "__main__":
    unittest.main()
