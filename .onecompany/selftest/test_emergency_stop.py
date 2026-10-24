from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import onecompany_lib
from onecompany_lib import emergency_stop_active

NO_EXTERNAL = {"ONECOMPANY_EMERGENCY_STOP": "", "ONECOMPANY_EMERGENCY_STOP_FILE": ""}


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


class EmergencyStopFailClosedVectors(unittest.TestCase):
    """OC-P0-10 (#343): ambiguous or malformed stop signals assert STOP."""

    def test_external_values(self):
        vectors = {
            "": False, "  ": False, "0": False, "false": False, " FALSE ": False,
            "no": False, "off": False, "Off": False,
            "1": True, "true": True, "yes": True, "on": True, "stop": True,
            "stopped": True, "enabled": True, "STOP!": True, "maybe": True,
            "2": True, "falsey": True,
        }
        for value, expected in vectors.items():
            with self.subTest(value=value):
                with patch.dict(os.environ, {**NO_EXTERNAL, "ONECOMPANY_EMERGENCY_STOP": value}):
                    self.assertIs(
                        emergency_stop_active({"safety": {"emergency_stop": False}}), expected)

    def test_config_values(self):
        vectors = [
            ({}, False),
            ({"safety": {}}, False),
            ({"safety": {"fail_closed_on_ambiguous_authority": True}}, False),
            ({"safety": {"emergency_stop": False}}, False),
            ({"safety": {"emergency_stop": True}}, True),
            ({"safety": {"emergency_stop": "true"}}, True),
            ({"safety": {"emergency_stop": "false"}}, True),
            ({"safety": {"emergency_stop": 1}}, True),
            ({"safety": {"emergency_stop": 0}}, True),
            ({"safety": {"emergency_stop": None}}, True),
            ({"safety": {"emergency_stop": []}}, True),
            ({"safety": True}, True),
            ({"safety": None}, True),
            ({"safety": ["emergency_stop"]}, True),
            ({"safety": "stop"}, True),
            ([], True),
            ("stop", True),
        ]
        for config, expected in vectors:
            with self.subTest(config=config):
                with patch.dict(os.environ, NO_EXTERNAL):
                    self.assertIs(emergency_stop_active(config), expected)

    def test_external_stop_wins_over_any_config(self):
        with patch.dict(os.environ, {**NO_EXTERNAL, "ONECOMPANY_EMERGENCY_STOP": "true"}):
            for config in ({}, {"safety": {"emergency_stop": False}}):
                self.assertTrue(emergency_stop_active(config))

    def _with_config_file(self, content: str | None) -> bool:
        with tempfile.TemporaryDirectory() as tmp:
            control = Path(tmp)
            if content is not None:
                (control / "config.json").write_text(content, encoding="utf-8")
            with patch.object(onecompany_lib, "CONTROL", control), patch.dict(os.environ, NO_EXTERNAL):
                return emergency_stop_active()

    def test_config_file_vectors(self):
        vectors = [
            ('{"safety": {"emergency_stop": false}}', False),
            ('{"safety": {"emergency_stop": true}}', True),
            ('{"safety": {"emergency_stop": "no"}}', True),
            (None, True),
            ("", True),
            ("{not json", True),
            ("[]", True),
            ("null", True),
        ]
        for content, expected in vectors:
            with self.subTest(content=content):
                self.assertIs(self._with_config_file(content), expected)

    def test_repository_config_is_currently_clear(self):
        with patch.dict(os.environ, NO_EXTERNAL):
            self.assertFalse(emergency_stop_active())


if __name__ == "__main__":
    unittest.main()
