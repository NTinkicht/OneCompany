from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class A3bDocumentationTests(unittest.TestCase):
    """Keep A3b's promotion evidence and safety boundary documented."""

    def test_documentation_records_live_smoke_and_copilot_fail_closed_state(self):
        text = (ROOT / "docs" / "A3B-ZERO-SPEND-ACTIONS-ADAPTER.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("35026542482", text)
        self.assertIn("3a0d2571ad9e655ff3b130f10fd787703f74f603", text)
        self.assertIn("no implementation capability", text)
        self.assertIn("monthly quota exceeded", text)
        self.assertIn("0 Premium", text)
        self.assertIn("remains disabled and unconfigured", text)


if __name__ == "__main__":
    unittest.main()
