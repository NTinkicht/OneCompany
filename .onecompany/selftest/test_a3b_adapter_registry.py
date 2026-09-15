from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import dispatch_execute_entry  # noqa: E402


class A3bAdapterRegistryTests(unittest.TestCase):
    """Keep the automatic adapter allowlist explicit and narrow."""

    def test_only_reviewed_a3b_mechanisms_are_in_registry(self):
        self.assertEqual(
            set(dispatch_execute_entry.ADAPTERS),
            {"onecompany-actions-readonly", "copilot-actions-readonly"},
        )


if __name__ == "__main__":
    unittest.main()
