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

    def test_installed_project_missing_repository_gets_specific_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "installed"; target.mkdir()
            control = target / ".onecompany"; control.mkdir()
            (control / "config.json").write_text(
                '{"project":{"repository":null}}', encoding="utf-8"
            )
            report = onboard.analyze(target)
            self.assertEqual(report["mode"], "INSTALLED")
            self.assertEqual(report["journey"]["steps"][1]["status"],
                             "needs_attention")
            self.assertIn("repair the configured repository",
                          report["journey"]["next_action"])
            self.assertFalse(report["journey"]["application_authorized"])

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

    def test_symlinked_or_non_directory_framework_paths_block_apply(self):
        """Assessment must refuse exactly what bootstrap preflight refuses."""
        def dangling_file(target: Path, outside: Path) -> None:
            (target / "AGENTS.md").symlink_to(target / "missing-agents.md")

        def directory_link_outside(target: Path, outside: Path) -> None:
            (target / "scripts").symlink_to(outside, target_is_directory=True)

        def directory_link_inside(target: Path, outside: Path) -> None:
            (target / "src").mkdir()
            (target / "docs").symlink_to(target / "src", target_is_directory=True)

        def dangling_directory_link(target: Path, outside: Path) -> None:
            (target / "agents").symlink_to(target / "missing-agents-dir", target_is_directory=True)

        def file_in_place_of_directory(target: Path, outside: Path) -> None:
            (target / "docs").write_text("product notes, not a directory\n", encoding="utf-8")

        cases = (
            ("dangling_file", dangling_file, "AGENTS.md"),
            ("directory_link_outside", directory_link_outside, "scripts"),
            ("directory_link_inside", directory_link_inside, "docs"),
            ("dangling_directory_link", dangling_directory_link, "agents"),
            ("file_in_place_of_directory", file_in_place_of_directory, "docs"),
        )
        for name, setup, expected in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as temp:
                outside = Path(temp) / "outside"; outside.mkdir()
                target = Path(temp) / "app"; target.mkdir()
                (target / "README.md").write_text("product\n", encoding="utf-8")
                setup(target, outside)
                before = sorted((p.relative_to(Path(temp)).as_posix(), p.is_symlink()) for p in Path(temp).rglob("*"))
                report = onboard.analyze(target, repository="example/app")
                self.assertEqual(report["mode"], "ADOPT_EXISTING")
                self.assertIn(expected, report["collisions"])
                self.assertFalse(report["can_apply"])
                self.assertIn("Existing files collide with OneCompany framework paths; resolve them before --apply", report["blockers"])
                self.assertTrue(report["journey"]["safety_blockers"])
                self.assertFalse(report["journey"]["write_lease_granted"])
                after = sorted((p.relative_to(Path(temp)).as_posix(), p.is_symlink()) for p in Path(temp).rglob("*"))
                self.assertEqual(before, after, "assessment must not mutate the target or the link destination")
                self.assertEqual(list(outside.iterdir()), [])

    def test_unrelated_symlink_does_not_block_clean_target(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "app"; target.mkdir()
            (target / "README.md").write_text("product\n", encoding="utf-8")
            (target / "lib").mkdir()
            (target / "current").symlink_to(target / "lib", target_is_directory=True)
            report = onboard.analyze(target, repository="example/app")
            self.assertEqual(report["collisions"], [])
            self.assertTrue(report["can_apply"])


if __name__ == "__main__":
    unittest.main()
