from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from onecompany_lib import emergency_stop_active


class EmergencyStopTests(unittest.TestCase):
    def test_repository_stop_is_honored(self):
        self.assertTrue(emergency_stop_active({"safety": {"emergency_stop": True}}))

    def test_external_environment_stop_overrides_repository_clear(self):
        with patch.dict(os.environ, {"ONECOMPANY_EMERGENCY_STOP": "true"}, clear=False):
            self.assertTrue(emergency_stop_active({"safety": {"emergency_stop": False}}))

    def test_external_sentinel_file_overrides_repository_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            sentinel = Path(tmp) / "STOP"
            sentinel.write_text("incident containment\n", encoding="utf-8")
            with patch.dict(os.environ, {"ONECOMPANY_EMERGENCY_STOP_FILE": str(sentinel)}, clear=False):
                self.assertTrue(emergency_stop_active({"safety": {"emergency_stop": False}}))

    def test_no_signal_is_clear(self):
        with patch.dict(os.environ, {"ONECOMPANY_EMERGENCY_STOP": "", "ONECOMPANY_EMERGENCY_STOP_FILE": ""}, clear=False):
            self.assertFalse(emergency_stop_active({"safety": {"emergency_stop": False}}))


if __name__ == "__main__":
    unittest.main()
