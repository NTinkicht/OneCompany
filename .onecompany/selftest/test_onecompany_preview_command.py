"""Real source-checkout preview-local entrypoint and actual localhost HTTP smoke."""
import importlib.util
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time
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
        """Document the port argument and reject unexpected CLI options."""
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
        """Delegate to the one existing app without starting a second server."""
        spec = importlib.util.spec_from_file_location("onecompany_preview_entrypoint", ENTRY)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with mock.patch.object(sys, "argv", ["onecompany.py", "preview-local", "--port", "0"]), \
             mock.patch.object(module.subprocess, "Popen") as spawn:
            spawn.return_value.wait.return_value = 3
            self.assertEqual(module.main(), 3)
        self.assertEqual(spawn.call_args.args[0],
                         [sys.executable, str(ROOT / "scripts" / ".." / "examples" / "vertical-slice" / "app.py"), "--port", "0"])
        self.assertEqual(spawn.call_args.kwargs["cwd"], str(ROOT))

    @unittest.skipUnless(os.name == "posix", "SIGINT shutdown integration is POSIX-specific")
    def test_real_start_health_page_and_sigint_cleanup(self):
        """Verify real HTTP and wrapper-to-child Ctrl+C disposal with bounded waits."""
        proc = subprocess.Popen(
            [sys.executable, str(ENTRY), "preview-local", "--port", "0"],
            cwd=ROOT, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            # Buffered readline() can hang forever on partial output even after
            # select() indicates readiness. Read bounded bytes until newline.
            startup = b""
            deadline = time.monotonic() + 6
            with selectors.DefaultSelector() as selector:
                selector.register(proc.stdout, selectors.EVENT_READ)
                while b"\\n" not in startup and time.monotonic() < deadline:
                    if not selector.select(timeout=max(0, deadline - time.monotonic())):
                        break
                    chunk = os.read(proc.stdout.fileno(), 1024)
                    if not chunk:
                        break
                    startup += chunk
                    if len(startup) > 4096:
                        break
            if b"\\n" not in startup:
                self.fail("local preview did not emit a complete startup URL within 6 seconds")
            line = startup.split(b"\\n", 1)[0].decode("utf-8")
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
            self.assertEqual(proc.returncode, 0, "preview-local must handle SIGINT as a clean shutdown")


if __name__ == "__main__":
    unittest.main()
