from __future__ import annotations
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("onboard", ROOT / "scripts" / "onboard.py")
assert SPEC and SPEC.loader
onboard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(onboard)


class OnboardTests(unittest.TestCase):
    def test_empty_target_is_new_project(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "new-product"
            report = onboard.analyze(target, repository="example/new-product")
            self.assertEqual(report["mode"], "NEW_PROJECT")
            self.assertTrue(report["can_apply"])
            self.assertEqual(report["safe_defaults"]["autonomy"], "L1")

    def test_existing_stack_is_detected_without_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "app"; target.mkdir()
            (target / "package.json").write_text("{}", encoding="utf-8")
            (target / "tests").mkdir()
            report = onboard.analyze(target, repository="example/app")
            self.assertEqual(report["mode"], "ADOPT_EXISTING")
            self.assertIn("Node/TypeScript", report["stack"])
            self.assertIn("tests", report["tests"])
            self.assertFalse((target / ".onecompany").exists())

    def test_framework_path_collision_blocks_apply(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "app"; (target / "scripts").mkdir(parents=True)
            (target / "scripts" / "validate.py").write_text("# product-owned\n", encoding="utf-8")
            report = onboard.analyze(target, repository="example/app")
            self.assertFalse(report["can_apply"])
            self.assertIn("scripts/validate.py", report["collisions"])


if __name__ == "__main__":
    unittest.main()
