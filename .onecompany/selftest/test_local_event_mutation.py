from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import local_event_mutation as mutation  # noqa: E402


class LocalEventMutationTests(unittest.TestCase):
    """The local append boundary marks uncertainty only after open succeeds."""

    def target(self, directory: str) -> Path:
        return Path(directory) / "events.jsonl"

    def test_pre_write_mkdir_failure_remains_plain_oserror(self):
        with tempfile.TemporaryDirectory() as directory:
            target = self.target(directory)
            with patch.object(Path, "mkdir", side_effect=OSError("mkdir failed")):
                with self.assertRaisesRegex(OSError, "mkdir failed"):
                    mutation.append_local_event("TEST", "actor", {}, path=target)

    def test_pre_write_existing_log_failure_remains_plain_runtime_error(self):
        with tempfile.TemporaryDirectory() as directory:
            target = self.target(directory)
            with patch.object(
                mutation.lifecycle,
                "local_events",
                side_effect=RuntimeError("corrupt log"),
            ):
                with self.assertRaisesRegex(RuntimeError, "corrupt log"):
                    mutation.append_local_event("TEST", "actor", {}, path=target)

    def test_pre_write_open_failure_remains_plain_oserror(self):
        with tempfile.TemporaryDirectory() as directory:
            target = self.target(directory)
            with patch.object(Path, "open", side_effect=OSError("open failed")):
                with self.assertRaisesRegex(OSError, "open failed"):
                    mutation.append_local_event("TEST", "actor", {}, path=target)

    def test_write_failure_is_explicitly_uncertain(self):
        handle = MagicMock()
        handle.__enter__.return_value = handle
        handle.__exit__.return_value = False
        handle.write.side_effect = OSError("write failed")
        with tempfile.TemporaryDirectory() as directory:
            target = self.target(directory)
            with (
                patch.object(mutation.lifecycle, "local_events", return_value=[]),
                patch.object(Path, "open", return_value=handle),
            ):
                with self.assertRaisesRegex(
                    mutation.LocalEventMutationUncertainError,
                    "write failed",
                ):
                    mutation.append_local_event("TEST", "actor", {}, path=target)

    def test_flush_failure_is_explicitly_uncertain(self):
        handle = MagicMock()
        handle.__enter__.return_value = handle
        handle.__exit__.return_value = False
        handle.write.side_effect = lambda value: len(value)
        handle.flush.side_effect = OSError("flush failed")
        with tempfile.TemporaryDirectory() as directory:
            target = self.target(directory)
            with (
                patch.object(mutation.lifecycle, "local_events", return_value=[]),
                patch.object(Path, "open", return_value=handle),
            ):
                with self.assertRaisesRegex(
                    mutation.LocalEventMutationUncertainError,
                    "flush failed",
                ):
                    mutation.append_local_event("TEST", "actor", {}, path=target)


if __name__ == "__main__":
    unittest.main()
