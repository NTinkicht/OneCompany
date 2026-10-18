import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from live_work_reconciliation import WorkSnapshot, inconsistencies


class ReconciliationTests(unittest.TestCase):
    def test_consistent_snapshot(self):
        snap = WorkSnapshot("a" * 40, "a" * 40, (1, 2), (2,), ((9, 1),), (1,))
        self.assertEqual(inconsistencies(snap), ())

    def test_stale_orphan_duplicate_and_retired(self):
        snap = WorkSnapshot("a" * 40, "b" * 40, (1, 1), (2, 2), ((9, 3), (10, 3)), (4, 4), (2, 4))
        self.assertEqual(set(inconsistencies(snap)), {
            "STALE_MAIN", "DUPLICATE_ISSUE", "DUPLICATE_NEXT",
            "ORPHAN_NEXT", "ORPHAN_PR", "ORPHAN_LEASE",
            "DUPLICATE_PR_BINDING", "DUPLICATE_LEASE",
            "RETIRED_PILOT_REACTIVATED",
        })


if __name__ == "__main__":
    unittest.main()
