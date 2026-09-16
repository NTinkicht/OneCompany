from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import gate  # noqa: E402


class ExactStateKnowledgeEvidenceTests(unittest.TestCase):
    def test_live_gate_context_rejects_mismatched_exact_head(self):
        reviewed = "a" * 40
        live_head = "b" * 40
        live = {
            "state": "OPEN",
            "isDraft": False,
            "headRefOid": live_head,
            "baseRefOid": "c" * 40,
        }
        with patch.object(gate, "live_pr", return_value=(live, None)):
            value, error = gate._live_context("owner/repo", 1, reviewed)
        self.assertIsNone(value)
        self.assertIsNotNone(error)
        self.assertIn("exact-head mismatch", str(error))
        self.assertIn(live_head, str(error))
        self.assertIn(reviewed, str(error))


if __name__ == "__main__":
    unittest.main()
