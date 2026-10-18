import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from live_work_reconciliation import WorkSnapshot, inconsistencies

SHA = "a" * 40


def snap(**overrides):
    """Consistent baseline snapshot; each test perturbs exactly one aspect."""
    fields = dict(
        main_sha=SHA,
        observed_main_sha=SHA,
        issue_ids=(1, 2, 3),
        next_ids=(2,),
        pr_issue_bindings=((9, 1),),
        active_lease_issue_ids=(1,),
        retired_pilot_issue_ids=(),
    )
    fields.update(overrides)
    return WorkSnapshot(**fields)


class ReconciliationTests(unittest.TestCase):
    def assertOnly(self, snapshot, finding):
        self.assertEqual(inconsistencies(snapshot), (finding,))

    def test_consistent_snapshot(self):
        self.assertEqual(inconsistencies(snap()), ())

    def test_stale_main(self):
        self.assertOnly(snap(observed_main_sha="b" * 40), "STALE_MAIN")

    def test_empty_main_sha_fails_closed(self):
        self.assertOnly(snap(main_sha="", observed_main_sha=""), "STALE_MAIN")

    def test_duplicate_issue(self):
        self.assertOnly(snap(issue_ids=(1, 2, 3, 3)), "DUPLICATE_ISSUE")

    def test_duplicate_next(self):
        self.assertOnly(snap(next_ids=(2, 2)), "DUPLICATE_NEXT")

    def test_orphan_next(self):
        self.assertOnly(snap(next_ids=(2, 7)), "ORPHAN_NEXT")

    def test_orphan_pr(self):
        self.assertOnly(snap(pr_issue_bindings=((9, 1), (10, 7))), "ORPHAN_PR")

    def test_orphan_lease(self):
        self.assertOnly(snap(active_lease_issue_ids=(1, 7)), "ORPHAN_LEASE")

    def test_same_issue_bound_to_multiple_prs(self):
        self.assertOnly(snap(pr_issue_bindings=((9, 1), (10, 1))), "DUPLICATE_PR_BINDING")

    def test_same_pr_bound_to_multiple_issues(self):
        self.assertOnly(snap(pr_issue_bindings=((9, 1), (9, 3))), "DUPLICATE_PR_BINDING")

    def test_duplicate_lease(self):
        self.assertOnly(snap(active_lease_issue_ids=(1, 1)), "DUPLICATE_LEASE")

    def test_leased_issue_in_next(self):
        self.assertOnly(snap(next_ids=(2, 3), active_lease_issue_ids=(1, 3)), "ACTIVE_WORK_IN_NEXT")

    def test_pr_bound_issue_in_next(self):
        self.assertOnly(snap(next_ids=(2, 3), pr_issue_bindings=((9, 1), (10, 3))), "ACTIVE_WORK_IN_NEXT")

    def test_retired_pilot_in_next(self):
        self.assertOnly(snap(retired_pilot_issue_ids=(2,)), "RETIRED_PILOT_REACTIVATED")

    def test_retired_pilot_with_active_lease(self):
        self.assertOnly(snap(issue_ids=(1, 2, 3), active_lease_issue_ids=(1, 3), retired_pilot_issue_ids=(3,)),
                        "RETIRED_PILOT_REACTIVATED")

    def test_retired_pilot_not_active_is_consistent(self):
        self.assertEqual(inconsistencies(snap(retired_pilot_issue_ids=(3,))), ())

    def test_combined_adversarial_snapshot(self):
        bad = WorkSnapshot("a" * 40, "b" * 40, (1, 1), (2, 2), ((9, 3), (10, 3)), (4, 4), (2, 4))
        self.assertEqual(set(inconsistencies(bad)), {
            "STALE_MAIN", "DUPLICATE_ISSUE", "DUPLICATE_NEXT",
            "ORPHAN_NEXT", "ORPHAN_PR", "ORPHAN_LEASE",
            "DUPLICATE_PR_BINDING", "DUPLICATE_LEASE",
            "RETIRED_PILOT_REACTIVATED",
        })

    def test_findings_are_sorted_and_stable(self):
        bad = snap(observed_main_sha="b" * 40, next_ids=(2, 2))
        self.assertEqual(inconsistencies(bad), ("DUPLICATE_NEXT", "STALE_MAIN"))
        self.assertEqual(inconsistencies(bad), inconsistencies(bad))


if __name__ == "__main__":
    unittest.main()
