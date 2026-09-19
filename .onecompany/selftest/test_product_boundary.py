from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_product_neutrality.py"
SPEC = importlib.util.spec_from_file_location("product_neutrality", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
neutrality = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(neutrality)


class ProductBoundaryTests(unittest.TestCase):
    def test_target_evidence_roots_are_not_distributed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            problems = neutrality.find_violations([
                "source-evidence/client/snapshot.json",
                "evidence/client/release.json",
                "docs/PRODUCT-BOUNDARY.md",
            ], Path(temp))
        self.assertEqual(len(problems), 2)

    def test_synthetic_fixtures_are_namespaced_and_labelled(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            relative = ".onecompany/selftest/fixtures/sample.json"
            file = root / relative
            file.parent.mkdir(parents=True)
            sample = {
                "project": {"repository": "example/sample", "default_branch": "main"},
                "snapshot": {"source": "fixture-synthetic-read-only"},
                "fixture_note": "Synthetic test case",
            }
            file.write_text(json.dumps(sample), encoding="utf-8")
            self.assertEqual(neutrality.find_violations([relative], root), [])
            sample["project"]["repository"] = "customer/private-application"
            file.write_text(json.dumps(sample), encoding="utf-8")
            self.assertTrue(neutrality.find_violations([relative], root))
            sample["project"]["repository"] = "example/sample"
            sample["snapshot"]["source"] = "github-live"
            file.write_text(json.dumps(sample), encoding="utf-8")
            self.assertTrue(neutrality.find_violations([relative], root))

    def test_reusable_repo_current_checkout_is_clean(self) -> None:
        self.assertEqual(neutrality.main(), 0)


if __name__ == "__main__":
    unittest.main()
