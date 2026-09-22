"""Real Phase-1 Create/Adopt to in-memory HTTP CRUD integration tests."""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import phase1_vertical_smoke as vertical
from onboard import analyze
from product_brief import make_draft

HEAD = "a" * 40
BASE = "b" * 40
ANSWERS = {
    "audience": "Families",
    "problem": "Track small daily tasks",
    "outcome": "See a local checklist",
    "first_feature": "Add, complete and delete a checklist item",
    "constraints": "No patient or production data",
}


class Phase1VerticalSmokeTests(unittest.TestCase):
    """Prove actual network/SQLite fixture without making execution claims."""

    def test_create_mode_real_crud_with_disposable_server(self):
        """Create must run real app tests and leave target untouched."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "new"
            assessment = analyze(target, repository="demo/new")
            original = make_draft(assessment, ANSWERS)
            result = vertical.run(assessment, original, HEAD, BASE)
            self.assertEqual(result["path"], "create")
            self.assertEqual(result["status"], "LOCAL_FIXTURE_PROVEN_ONLY")
            self.assertEqual(result["real_local_http"]["status"], "PASS")
            self.assertEqual(result["real_local_http"]["health"], "PASS")
            self.assertTrue(result["real_local_http"]["fixture_discarded"])
            self.assertFalse(result["owner_implementation_approved"])
            self.assertFalse(result["browser_qualification_in_this_run"])
            self.assertFalse(result["exact_head_ci_verified_in_this_run"])
            self.assertFalse(result["independent_review_in_this_run"])
            self.assertIsNone(result["run_key"])
            self.assertIsNone(result["lease_id"])
            self.assertIsNone(result["canonical_work_unit"])
            self.assertFalse(target.exists())

    def test_adopt_mode_preserves_existing_assets_and_no_mutation(self):
        """Adopt must only inspect existing test/CI/contract files."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "existing"
            target.mkdir()
            (target / "pyproject.toml").write_text("[project]\nname='fixture'\n")
            (target / "tests").mkdir()
            (target / "SECURITY.md").write_text("example")
            assessment = analyze(target, repository="demo/existing")
            draft = make_draft(assessment, ANSWERS)
            before = sorted(p.relative_to(target).as_posix()
                            for p in target.rglob("*"))
            result = vertical.run(assessment, draft, HEAD, BASE)
            after = sorted(p.relative_to(target).as_posix()
                           for p in target.rglob("*"))
            self.assertEqual(result["path"], "adopt")
            self.assertIn("tests", result["project"]["tests"])
            self.assertIn("SECURITY.md", result["project"]["contracts"])
            self.assertEqual(before, after)

    def test_stale_and_authority_bearing_brief_refuses_before_server(self):
        """Untrusted draft cannot create a real app run or claim authority."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "project"
            assessment = analyze(target, repository="demo/project")
            draft = make_draft(assessment, ANSWERS)
            invalid = dict(draft)
            invalid["approval"] = dict(draft["approval"])
            invalid["approval"]["implementation"] = True
            with patch.object(vertical, "_local_app",
                              side_effect=AssertionError("server was started")):
                with self.assertRaisesRegex(ValueError, "STALE_OR_AUTHORITY"):
                    vertical.run(assessment, invalid, HEAD, BASE)
                with self.assertRaisesRegex(ValueError, "EXACT_DISTINCT"):
                    vertical.run(assessment, draft, HEAD, HEAD)
                missing = make_draft(assessment, {})
                with self.assertRaisesRegex(ValueError, "COMPLETE_OWNER_BRIEF"):
                    vertical.run(assessment, missing, HEAD, BASE)

    def test_actual_cli_with_saved_draft_and_unverified_ref_labels(self):
        """End-user CLI reports local proof without asserting live authority."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "future"
            assessment = analyze(target, repository="demo/future")
            saved = Path(tmp) / "draft.json"
            saved.write_text(json.dumps(make_draft(assessment, ANSWERS)))
            with contextlib.redirect_stdout(io.StringIO()) as output:
                code = vertical.main([
                    "--target", str(target), "--repository", "demo/future",
                    "--brief", str(saved), "--head", HEAD, "--base", BASE,
                ])
            self.assertEqual(code, 0)
            report = json.loads(output.getvalue())
            self.assertEqual(report["source_refs_unverified"],
                             {"head": HEAD, "base": BASE})
            self.assertEqual(report["planning"]["authorization"], "NOT_GRANTED")
            self.assertFalse(report["deployable"])
            self.assertEqual(report["requested_extra_spend"], 0)
            self.assertFalse(target.exists())

    def test_invalid_refs_and_missing_brief_never_launch_fixture(self):
        """Basic input validation fails before any HTTP listener starts."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "future"
            assessment = analyze(target, repository="demo/future")
            draft = make_draft(assessment, ANSWERS)
            with patch.object(vertical, "_local_app",
                              side_effect=AssertionError("server started")):
                with self.assertRaises(ValueError):
                    vertical.run(assessment, draft, "xyz", BASE)
                with contextlib.redirect_stderr(io.StringIO()):
                    code = vertical.main([
                        "--target", str(target), "--repository", "demo/future",
                        "--brief", str(Path(tmp) / "missing.json"),
                        "--head", HEAD, "--base", BASE,
                    ])
                self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
