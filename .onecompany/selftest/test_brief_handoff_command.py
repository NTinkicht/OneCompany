import json
import subprocess
import tempfile
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class BriefHandoffCommandTests(unittest.TestCase):
    def test_help_exposes_read_only_brief_handoff(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "onecompany.py"), "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("brief-handoff", result.stdout)
        self.assertIn("read-only planning handoff", result.stdout)

    def saved_brief(self):
        return {
            "document_kind": "product_brief_draft",
            "status": "DRAFT_NOT_APPROVED",
            "approval": {"product_brief": False, "implementation": False,
                         "deployment": False},
            "write_lease_granted": False,
            "qualified_implementer_selected": False,
            "acceptance_criteria": [], "safety_blockers": [],
            "missing_required_answers": [],
            "answers": {"audience": "Families", "problem": "Missed tasks",
                        "outcome": "Visible checklist",
                        "first_feature": "Create a task"},
            "project": {"name": "Demo", "repository": "owner/demo",
                        "default_branch": "main", "path": "create",
                        "known_stack": [], "existing_tests": [],
                        "existing_ci": [], "known_contracts": []},
        }

    def run_handoff(self, brief):
        return subprocess.run(
            [sys.executable, str(ROOT / "onecompany.py"),
             "brief-handoff", "--brief", str(brief),
             "--head", "a" * 40, "--base", "b" * 40],
            cwd=ROOT, capture_output=True, text=True, check=False, timeout=20,
        )

    def test_real_cli_produces_authority_free_proposal(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "saved.json"
            path.write_text(json.dumps(self.saved_brief()), encoding="utf-8")
            result = self.run_handoff(path)
        self.assertEqual(result.returncode, 0, result.stderr)
        proposal = json.loads(result.stdout)
        self.assertEqual(proposal["authorization"], "NOT_GRANTED")
        self.assertIsNone(proposal["lease_id"])
        self.assertIsNone(proposal["canonical_work_unit"])
        self.assertTrue(proposal["read_only"])

    def test_real_cli_refuses_symlinked_saved_brief(self):
        with tempfile.TemporaryDirectory() as td:
            real = Path(td) / "real.json"
            real.write_text(json.dumps(self.saved_brief()), encoding="utf-8")
            link = Path(td) / "brief.json"
            try:
                link.symlink_to(real)
            except (OSError, NotImplementedError):
                self.skipTest("symlink unsupported")
            result = self.run_handoff(link)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_brief_handoff_routes_to_existing_helper(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "onecompany.py"), "brief-handoff", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        combined = result.stdout + result.stderr
        self.assertNotIn("unknown command", combined)
        self.assertIn("brief", combined.lower())


if __name__ == "__main__":
    unittest.main()
