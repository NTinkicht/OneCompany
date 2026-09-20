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
    def test_empty_target_is_new_project_without_creation(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "new-product"
            self.assertFalse(target.exists())
            report = onboard.analyze(target, repository="example/new-product")
            self.assertEqual(report["mode"], "NEW_PROJECT")
            self.assertTrue(report["can_apply"])
            self.assertEqual(report["safe_defaults"]["autonomy"], "L1")
            self.assertFalse(target.exists(), "read-only assessment must not create the target directory")

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


    def test_new_idea_has_unapproved_guided_draft_without_fs_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "brand-new"
            report = onboard.analyze(target, repository="owner/brand-new")
            journey = report["journey"]
            self.assertEqual(journey["path"], "create")
            self.assertEqual([p["id"] for p in journey["steps"][:3]],
                             ["choose", "discover", "brief"])
            self.assertEqual(journey["steps"][2]["status"], "needs_input")
            self.assertEqual(journey["product_brief_draft"]["status"],
                             "DRAFT_NOT_APPROVED")
            self.assertFalse(journey["application_authorized"])
            self.assertFalse(journey["actor_qualified"])
            self.assertFalse(journey["write_lease_granted"])
            self.assertIsNone(journey["product_brief_draft"]["first_feature"])
            self.assertEqual(sum(q["required"] for q in journey["clarifying_questions"]), 3)
            self.assertFalse(target.exists())

    def test_existing_product_is_preserved_in_discovery_not_assumed_approved(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "existing"
            target.mkdir()
            (target / "pyproject.toml").write_text("[project]\nname='demo'\n")
            (target / "tests").mkdir()
            report = onboard.analyze(target, repository="owner/existing")
            draft = report["journey"]["product_brief_draft"]
            self.assertEqual(report["journey"]["path"], "adopt")
            self.assertEqual(draft["origin"], "existing_repository")
            self.assertIn("Python", draft["known_stack"])
            self.assertIn("tests", draft["existing_tests"])
            self.assertFalse(draft["approved"])
            self.assertIsNone(draft["audience"])
            self.assertFalse((target / ".onecompany").exists())

    def test_missing_repository_or_collision_stays_blocked_without_fake_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "existing"; target.mkdir()
            (target / "AGENTS.md").write_text("product-owned")
            report = onboard.analyze(target)
            journey = report["journey"]
            self.assertFalse(report["can_apply"])
            self.assertEqual(journey["steps"][1]["status"], "needs_attention")
            self.assertIn("Resolve", journey["next_action"])
            self.assertTrue(journey["safety_blockers"])
            self.assertFalse(journey["write_lease_granted"])
            self.assertEqual((target / "AGENTS.md").read_text(), "product-owned")


if __name__ == "__main__":
    unittest.main()
