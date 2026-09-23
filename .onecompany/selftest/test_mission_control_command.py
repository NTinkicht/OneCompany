"""Integration coverage for the one-command Mission Control entry point."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]


class MissionControlCommandTests(unittest.TestCase):
    def test_command_serves_real_loopback_http_without_mutating_input(self):
        projection = {
            "schema": "onecompany.mission-control.phase1.v1",
            "authority_granted": False,
            "project": {"name": "Example"},
            "readiness": "READY_FOR_OWNER_PREVIEW",
            "checks": {"quality": {"status": "PASS"}, "preview": {"status": "OBSERVED"}},
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "projection.json"
            path.write_text(json.dumps(projection), encoding="utf-8")
            before = path.read_bytes()
            proc = subprocess.Popen(
                [sys.executable, str(ROOT / "onecompany.py"), "mission-control",
                 "--input", str(path), "--port", "0"],
                cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            try:
                line = proc.stdout.readline().strip()
                self.assertTrue(line.startswith("Mission Control: http://127.0.0.1:"), line)
                url = line.split("Mission Control: ", 1)[1]
                last_error = None
                for _ in range(20):
                    try:
                        with urlopen(url, timeout=1) as response:
                            body = response.read().decode("utf-8")
                        break
                    except OSError as exc:
                        last_error = exc
                        time.sleep(0.05)
                else:
                    self.fail(f"Mission Control HTTP unavailable: {last_error}")
                self.assertIn("Mission Control", body)
                self.assertIn("No execution or deployment authority is granted", body)
                self.assertEqual(path.read_bytes(), before)
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill(); proc.wait(timeout=3)

    def test_bad_projection_is_bounded_refusal(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad.json"
            path.write_text("[]", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(ROOT / "onecompany.py"), "mission-control",
                 "--input", str(path), "--port", "0"],
                cwd=ROOT, text=True, capture_output=True, timeout=8,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("BLOCKED:", result.stderr)


if __name__ == "__main__":
    unittest.main()
