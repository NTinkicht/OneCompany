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
        self.assertFalse(any(doc.name.startswith("TARGET-INSTANCE-")
                             for doc in (ROOT / "docs").glob("*.md")))

    def test_shipped_guidance_does_not_bind_to_other_owner_projects(self):
        # Infer source owner dynamically; never bake an individual user's
        # project names into this generic framework regression.
        source = json.loads((ROOT / ".onecompany" / "config.json").read_text())
        owner, framework_repo = source["project"]["repository"].split("/", 1)
        candidates = [ROOT / "README.md", ROOT / "BOOTSTRAP.md"]
        for dirname in ("docs", "patterns", "overlays", "examples"):
            candidates.extend((ROOT / dirname).rglob("*.md"))
            candidates.extend((ROOT / dirname).rglob("*.json"))
        for path in candidates:
            content = path.read_text(encoding="utf-8")
            import re
            refs = re.findall(rf"\\b{re.escape(owner)}/([a-zA-Z0-9_.-]+)", content)
            self.assertFalse(
                [name for name in refs if name.lower() != framework_repo.lower()],
                f"other project reference in {path.relative_to(ROOT)}",
            )

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
