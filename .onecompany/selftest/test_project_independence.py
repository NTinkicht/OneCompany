"""Reusable source distribution must not carry any target instance's evidence."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ProjectIndependenceTests(unittest.TestCase):
    def test_no_project_instance_evidence_in_framework(self):
        # These directories are valid *inside an installed target* only.
        for path in ("source-evidence", "evidence"):
            self.assertFalse((ROOT / path).exists(), f"source distribution includes {path}")

    def test_framework_documents_use_generic_contracts(self):
        self.assertTrue((ROOT / "docs" / "PRODUCT-INDEPENDENCE.md").is_file())
        self.assertTrue((ROOT / "docs" / "OPERATING-LESSONS.md").is_file())
        self.assertFalse((ROOT / "docs" / "VERITAS-ACTIVATION.md").exists())
        self.assertFalse((ROOT / "docs" / "TABIBI-LESSONS.md").exists())

    def test_shadow_fixtures_use_distinct_synthetic_repositories(self):
        fixture_dir = ROOT / ".onecompany" / "selftest" / "fixtures"
        fixtures = list(fixture_dir.glob("*-blocked-shadow.json"))
        self.assertEqual(len(fixtures), 2)
        identities = set()
        for path in fixtures:
            value = json.loads(path.read_text(encoding="utf-8"))
            identity = value["project"]["repository"]
            self.assertTrue(identity.startswith("example/"), path.name)
            self.assertNotIn("github.com", path.read_text(encoding="utf-8"))
            identities.add(identity)
        self.assertEqual(len(identities), len(fixtures))


if __name__ == "__main__":
    unittest.main()
