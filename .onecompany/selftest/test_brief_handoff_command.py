import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class BriefHandoffCommandTests(unittest.TestCase):
    def test_help_exposes_read_only_brief_handoff(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "onecompany.py"), "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("brief-handoff", result.stdout)
        self.assertIn("read-only planning handoff", result.stdout)

    def test_brief_handoff_routes_to_existing_helper(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "onecompany.py"), "brief-handoff", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        combined = result.stdout + result.stderr
        self.assertNotIn("unknown command", combined)
        self.assertIn("brief", combined.lower())


if __name__ == "__main__":
    unittest.main()
