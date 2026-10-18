import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from live_work_reconciliation import (
    PullRequestObservation,
    WorkSnapshot,
    inconsistencies,
    pr_inconsistencies,
)

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

    def test_retired_pilot_with_pr_binding(self):
        self.assertOnly(snap(pr_issue_bindings=((9, 1), (10, 3)), retired_pilot_issue_ids=(3,)),
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


HEAD = "c" * 40
OLD_HEAD = "d" * 40


def pr(**overrides):
    """Consistent, merge-ready PR #9 bound to issue 1 on the live head."""
    fields = dict(
        pr=9,
        issue=1,
        recorded_head_sha=HEAD,
        observed_head_sha=HEAD,
        base_sha=SHA,
        approved_head_sha=HEAD,
        ci_head_sha=HEAD,
        ci_conclusion="success",
        merge_ready_claimed=True,
    )
    fields.update(overrides)
    return PullRequestObservation(**fields)


class PullRequestReconciliationTests(unittest.TestCase):
    def findings(self, *observations, snapshot=None):
        return pr_inconsistencies(snapshot or snap(), observations)

    def assertOnly(self, observation, finding):
        self.assertEqual(self.findings(observation), ((observation.pr, finding),))

    def test_consistent_merge_ready_pr(self):
        self.assertEqual(self.findings(pr()), ())

    def test_pending_review_and_ci_without_claim_is_consistent(self):
        self.assertEqual(self.findings(pr(approved_head_sha=None, ci_head_sha=None,
                                          ci_conclusion=None, merge_ready_claimed=False)), ())

    def test_no_observations(self):
        self.assertEqual(self.findings(), ())

    def test_stale_recorded_head(self):
        self.assertOnly(pr(recorded_head_sha=OLD_HEAD, merge_ready_claimed=False), "STALE_PR_HEAD")

    def test_base_behind_main(self):
        self.assertOnly(pr(base_sha="e" * 40, merge_ready_claimed=False), "BASE_BEHIND_MAIN")

    def test_approval_on_older_head(self):
        self.assertOnly(pr(approved_head_sha=OLD_HEAD, merge_ready_claimed=False), "STALE_APPROVAL")

    def test_ci_on_older_head(self):
        self.assertOnly(pr(ci_head_sha=OLD_HEAD, merge_ready_claimed=False), "STALE_CI")

    def test_failed_ci_on_head(self):
        self.assertOnly(pr(ci_conclusion="failure", merge_ready_claimed=False), "CI_NOT_GREEN")

    def test_pending_ci_on_head(self):
        self.assertOnly(pr(ci_conclusion=None, merge_ready_claimed=False), "CI_NOT_GREEN")

    def test_merge_ready_claim_without_approval(self):
        self.assertOnly(pr(approved_head_sha=None), "UNSUPPORTED_MERGE_READY")

    def test_merge_ready_claim_without_ci(self):
        self.assertOnly(pr(ci_head_sha=None, ci_conclusion=None), "UNSUPPORTED_MERGE_READY")

    def test_merge_ready_claim_with_stale_approval(self):
        self.assertEqual(self.findings(pr(approved_head_sha=OLD_HEAD)),
                         ((9, "STALE_APPROVAL"), (9, "UNSUPPORTED_MERGE_READY")))

    def test_pr_bound_to_other_issue(self):
        self.assertOnly(pr(issue=3), "PR_BINDING_MISMATCH")

    def test_unbound_pr(self):
        self.assertOnly(pr(pr=11), "PR_BINDING_MISMATCH")

    def test_duplicate_observation(self):
        self.assertEqual(self.findings(pr(), pr()), ((9, "DUPLICATE_PR_OBSERVATION"),))

    def test_malformed_shas_never_match_and_fail_closed(self):
        for bad in ("", "C" * 40, "c" * 39, "g" * 40, " " + "c" * 39):
            with self.subTest(sha=bad):
                found = set(self.findings(pr(recorded_head_sha=bad, observed_head_sha=bad,
                                              approved_head_sha=bad, ci_head_sha=bad)))
                self.assertTrue({(9, "INVALID_SHA"), (9, "STALE_PR_HEAD"), (9, "STALE_APPROVAL"),
                                 (9, "STALE_CI"), (9, "UNSUPPORTED_MERGE_READY")} <= found)

    def test_invalid_live_main_fails_base_check(self):
        snapshot = snap(main_sha="", observed_main_sha="")
        self.assertEqual(self.findings(pr(base_sha=""), snapshot=snapshot),
                         ((9, "BASE_BEHIND_MAIN"), (9, "INVALID_SHA"), (9, "UNSUPPORTED_MERGE_READY")))

    def test_findings_sorted_by_pr_then_code(self):
        snapshot = snap(pr_issue_bindings=((9, 1), (10, 3)))
        result = self.findings(pr(pr=10, issue=3, ci_conclusion="failure", merge_ready_claimed=False),
                               pr(base_sha="e" * 40), snapshot=snapshot)
        self.assertEqual(result, ((9, "BASE_BEHIND_MAIN"), (9, "UNSUPPORTED_MERGE_READY"),
                                  (10, "CI_NOT_GREEN")))
        self.assertEqual(result, self.findings(pr(base_sha="e" * 40),
                                               pr(pr=10, issue=3, ci_conclusion="failure",
                                                  merge_ready_claimed=False), snapshot=snapshot))


if __name__ == "__main__":
    unittest.main()
