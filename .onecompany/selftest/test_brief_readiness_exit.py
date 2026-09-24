import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
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

    def test_complete_unapproved_remains_authority_free_success(self):
        self.assertEqual(
            readiness_exit_code("DRAFT_COMPLETE_NOT_APPROVED", require_complete=True),
            0,
        )


if __name__ == "__main__":
    unittest.main()
