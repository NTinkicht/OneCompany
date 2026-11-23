import base64
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import required_checks  # noqa: E402

GOOD = json.dumps({"checks": [{"name": "validate"}]})


def payload(text: str) -> dict:
    return {"encoding": "base64", "content": base64.b64encode(text.encode()).decode()}


class TrustedManifestDuplicateKeyTests(unittest.TestCase):
    def load(self, text: str):
        with patch.object(required_checks, "_contents", return_value=(payload(text), None)):
            return required_checks._manifest_from_ref("o/r", "abc")

    def test_positive_control_loads(self):
        manifest, error = self.load(GOOD)
        self.assertIsNone(error)
        self.assertEqual(manifest["checks"][0]["name"], "validate")

    def test_duplicate_keys_refused_at_any_depth(self):
        top = GOOD.replace('{"checks"', '{"checks": [], "checks"', 1)
        nested = GOOD.replace('"name": "validate"', '"name": "other", "name": "validate"', 1)
        for bad in (top, nested):
            self.assertNotEqual(bad, GOOD)
            manifest, error = self.load(bad)
            self.assertIsNone(manifest)
            self.assertIn("duplicate key", error)


if __name__ == "__main__":
    unittest.main()
