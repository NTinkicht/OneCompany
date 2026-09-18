from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from execution_core import ExecutionStore  # noqa: E402


class ExecutionStorePathTests(unittest.TestCase):
    def test_unsafe_identifier_is_rejected_instead_of_aliasing(self):
        """Distinct WU IDs must never collapse onto one runtime artifact path."""
        with tempfile.TemporaryDirectory() as temp:
            store = ExecutionStore(Path(temp))
            valid = store.state_path("WU_A")
            self.assertEqual(valid.name, "WU_A.json")
            with self.assertRaisesRegex(ValueError, "work-unit id must match"):
                store.state_path("WU/A")

    def test_windows_reserved_device_names_are_rejected(self):
        """Runtime artifact names must stay regular files on Windows."""
        with tempfile.TemporaryDirectory() as temp:
            store = ExecutionStore(Path(temp))
            for wu_id in (
                "NUL",
                "nul",
                "CON.txt",
                "PRN.log",
                "AUX.",
                "COM1",
                "COM9.events",
                "LPT1",
                "LPT9.pending",
            ):
                with self.subTest(wu_id=wu_id):
                    with self.assertRaisesRegex(
                        ValueError, "Windows-reserved device basename"
                    ):
                        store.state_path(wu_id)

            self.assertEqual(store.state_path("COM10").name, "COM10.json")
            self.assertEqual(
                store.state_path("CONSOLE").name, "CONSOLE.json"
            )

    def test_distinct_safe_identifiers_have_distinct_artifact_paths(self):
        """Allowed identifiers remain one-to-one with their local filenames."""
        with tempfile.TemporaryDirectory() as temp:
            store = ExecutionStore(Path(temp))
            self.assertNotEqual(
                store.state_path("WU-A"),
                store.state_path("WU_A"),
            )
            self.assertNotEqual(
                store.journal_path("WU-A"),
                store.journal_path("WU_A"),
            )
            self.assertNotEqual(
                store.lock_path("WU-A"),
                store.lock_path("WU_A"),
            )


if __name__ == "__main__":
    unittest.main()
