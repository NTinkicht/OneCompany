import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
# Both imports are necessary for isolated execution: this test imports the
# scripts package, while its source-only helper uses bare sibling imports.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from scripts.brief_status import readiness_exit_code


class BriefReadinessExitTests(unittest.TestCase):
    def test_blocked_is_always_nonzero(self):
        self.assertEqual(readiness_exit_code("BLOCKED"), 2)
        self.assertEqual(readiness_exit_code("BLOCKED", require_complete=True), 2)

    def test_incomplete_is_nonzero_only_when_completion_is_required(self):
        self.assertEqual(readiness_exit_code("DRAFT_INCOMPLETE"), 0)
        self.assertEqual(
            readiness_exit_code("DRAFT_INCOMPLETE", require_complete=True),
            3,
        )

    def test_unrecognized_stage_fails_closed(self):
        self.assertEqual(readiness_exit_code("DRAFT_STALE", require_complete=True), 3)
        self.assertEqual(readiness_exit_code(None, require_complete=True), 3)
        self.assertEqual(readiness_exit_code("DRAFT_STALE"), 2)

    def test_real_cli_incomplete_exits_three(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "draft.json"
            path.write_text(json.dumps({
                "schema_version": "1.0",
                "document_kind": "product_brief_draft",
                "status": "DRAFT_NOT_APPROVED",
                "source": "owner_supplied_answers_and_read_only_discovery",
                "project": {"name": "Test"},
                "answers": {"problem": "P", "audience": "A",
                            "outcome": None, "first_feature": "F"},
                "missing_required_answers": ["outcome"],
                "acceptance_criteria": [],
                "approval": {"product_brief": False,
                             "implementation": False, "deployment": False},
                "write_lease_granted": False,
                "qualified_implementer_selected": False,
                "safety_blockers": [],
            }), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / "brief_status.py"),
                 str(path), "--require-complete"],
                capture_output=True, text=True, timeout=15,
            )
            self.assertEqual(result.returncode, 3, result.stderr)
            self.assertEqual(json.loads(result.stdout)["stage"], "DRAFT_INCOMPLETE")

    def test_complete_unapproved_remains_authority_free_success(self):
        self.assertEqual(
            readiness_exit_code("DRAFT_COMPLETE_NOT_APPROVED", require_complete=True),
            0,
        )


if __name__ == "__main__":
    unittest.main()
