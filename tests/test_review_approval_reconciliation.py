"""OC-P0-01 (#369): fail-closed approval attribution from exact-head reviews."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from live_work_reconciliation import (  # noqa: E402
    PullRequestObservation, WorkSnapshot, pr_inconsistencies,
)
from review_approval_reconciliation import (  # noqa: E402
    ReviewObservation, attribute_approval,
)

MAIN = "a" * 40
OLD_BASE = "b" * 40
HEAD = "c" * 40
OLD_HEAD = "d" * 40
BOT = "ntk-reviewer[bot]"
TRUSTED = (BOT,)


def marker(head=HEAD, mode="approve", base=MAIN, verdict="PASS"):
    base_part = f"base={base} " if base else ""
    return f"<!-- ntk-review v1 head={head} mode={mode} {base_part}verdict={verdict} floor=0 -->"


def review(id_, state="APPROVED", *, reviewer=BOT, commit=HEAD, body=None):
    if body is None:
        body = f"**ntk-reviewer** summary\n\n{marker(head=commit)}"
    return ReviewObservation(id_, reviewer, state, commit, body)


class ApprovalAttributionTests(unittest.TestCase):
    def attr(self, reviews, head=HEAD, trusted=TRUSTED):
        return attribute_approval(reviews, head, trusted)

    def triple(self, result):
        return (result.approved_head_sha, result.approved_base_sha, result.approved_by)

    def assertNoApproval(self, result, findings):
        self.assertEqual((None, None, None), self.triple(result))
        self.assertEqual(findings, result.findings)

    def test_trusted_approval_on_exact_head_with_base(self):
        result = self.attr((review(7),))
        self.assertEqual((HEAD, MAIN, BOT), self.triple(result))
        self.assertEqual((), result.findings)

    def test_no_reviews_is_no_approval_without_findings(self):
        self.assertNoApproval(self.attr(()), ())

    def test_later_change_request_supersedes_approval(self):
        result = self.attr((review(7), review(9, "CHANGES_REQUESTED",
                                                 body=marker(mode="approve", verdict="CHANGES_REQUIRED"))))
        self.assertNoApproval(result, (("9", "CHANGES_REQUESTED"),))

    def test_later_approval_supersedes_change_request(self):
        result = self.attr((review(9), review(7, "CHANGES_REQUESTED")))
        self.assertEqual((HEAD, MAIN, BOT), self.triple(result))

    def test_dismissed_and_commented_reviews_never_count(self):
        self.assertNoApproval(self.attr((review(7, "DISMISSED"),)), ())
        self.assertNoApproval(self.attr((review(7, "COMMENTED", body=marker(mode="comment")),)), ())
        # A dismissed later review does not hide an earlier change request.
        result = self.attr((review(5, "CHANGES_REQUESTED"), review(8, "DISMISSED")))
        self.assertNoApproval(result, (("5", "CHANGES_REQUESTED"),))

    def test_approval_on_another_head_is_stale(self):
        result = self.attr((review(7, commit=OLD_HEAD),))
        self.assertNoApproval(result, (("", "STALE_HEAD_APPROVAL"),))

    def test_untrusted_or_case_variant_reviewer_never_approves(self):
        for login in ("someone", "NTK-Reviewer[bot]", "ntk-reviewer"):
            with self.subTest(login=login):
                result = self.attr((review(7, reviewer=login),))
                self.assertNoApproval(result, (("7", "UNTRUSTED_REVIEWER_APPROVAL"),))
        # An untrusted approval is reported but does not block a trusted one.
        result = self.attr((review(7), review(8, reviewer="someone")))
        self.assertEqual((HEAD, MAIN, BOT), self.triple(result))
        self.assertEqual((("8", "UNTRUSTED_REVIEWER_APPROVAL"),), result.findings)

    def test_marker_defects_withhold_approval(self):
        cases = {
            "missing": ("approved, no marker", "INVALID_APPROVAL_MARKER"),
            "duplicate": (f"{marker()}\n{marker()}", "INVALID_APPROVAL_MARKER"),
            "forged in summary": (f"text {marker(head=OLD_HEAD)} more\n{marker()}",
                                  "INVALID_APPROVAL_MARKER"),
            "truncated": ("<!-- ntk-review v1 head=" + HEAD[:20], "INVALID_APPROVAL_MARKER"),
            "head mismatch": (marker(head=OLD_HEAD), "MARKER_HEAD_MISMATCH"),
            "comment mode": (marker(mode="comment"), "MARKER_NOT_APPROVE_MODE"),
            "no base": (marker(base=None), "APPROVAL_WITHOUT_BASE"),
        }
        for name, (body, finding) in cases.items():
            with self.subTest(name):
                self.assertNoApproval(self.attr((review(7, body=body),)), (("7", finding),))

    def test_marker_base_is_reported_for_drift_detection(self):
        result = self.attr((review(7, body=marker(base=OLD_BASE)),))
        self.assertEqual((HEAD, OLD_BASE, BOT), self.triple(result))

    def test_invalid_inputs_withhold_all_attribution(self):
        good = review(7)
        cases = {
            "bad head": (((good,), "C" * 40, TRUSTED), (("", "INVALID_SHA"),)),
            "no trusted": (((good,), HEAD, ()), (("", "INVALID_TRUSTED_REVIEWERS"),)),
            "padded trusted": (((good,), HEAD, (" " + BOT,)), (("", "INVALID_TRUSTED_REVIEWERS"),)),
            "list trusted": (((good,), HEAD, [BOT]), (("", "INVALID_TRUSTED_REVIEWERS"),)),
            "reviews list": (([good], HEAD, TRUSTED), (("", "INVALID_REVIEW"),)),
        }
        extra = {
            "bool id": (ReviewObservation(True, BOT, "APPROVED", HEAD, marker()), ""),
            "zero id": (review(0), ""),
            "duplicate id": (review(7, "CHANGES_REQUESTED"), "7"),
            "unknown state": (review(8, "PENDING"), "8"),
            "bad commit": (review(8, commit="x"), "8"),
            "padded login": (review(8, reviewer=BOT + " "), "8"),
            "null body": (ReviewObservation(8, BOT, "APPROVED", HEAD, None), "8"),
            "not a review": ({"id": 8}, ""),
        }
        for name, (bad, ref) in extra.items():
            cases[name] = (((good, bad), HEAD, TRUSTED), ((ref, "INVALID_REVIEW"),))
        for name, (args, findings) in cases.items():
            with self.subTest(name):
                self.assertNoApproval(attribute_approval(*args), findings)

    def test_findings_are_deterministic(self):
        reviews = (review(8, reviewer="x"), review(3, reviewer="y"), review(5, "CHANGES_REQUESTED"))
        first = self.attr(reviews)
        self.assertEqual(first, self.attr(tuple(reversed(reviews))))
        self.assertEqual(list(first.findings), sorted(first.findings))


class ApprovalFeedsPrReconciliationTests(unittest.TestCase):
    SNAPSHOT = WorkSnapshot(main_sha=MAIN, observed_main_sha=MAIN, issue_ids=(5,), next_ids=(),
                            pr_issue_bindings=((9, 5),), active_lease_issue_ids=(5,))

    def findings(self, reviews):
        approval = attribute_approval(reviews, HEAD, TRUSTED)
        obs = PullRequestObservation(
            pr=9, issue=5, recorded_head_sha=HEAD, observed_head_sha=HEAD, base_sha=MAIN,
            approved_head_sha=approval.approved_head_sha,
            approved_base_sha=approval.approved_base_sha,
            approved_by=approval.approved_by,
            ci_head_sha=HEAD, ci_base_sha=MAIN, ci_conclusion="success",
            merge_ready_claimed=True, material_authors=("NTinkicht",))
        return pr_inconsistencies(self.SNAPSHOT, (obs,), trusted_reviewers=TRUSTED)

    def test_attributed_approval_on_live_base_supports_merge_ready(self):
        self.assertEqual((), self.findings((review(7),)))

    def test_approval_on_drifted_base_is_stale(self):
        self.assertEqual(((9, "STALE_APPROVAL"), (9, "UNSUPPORTED_MERGE_READY")),
                         self.findings((review(7, body=marker(base=OLD_BASE)),)))

    def test_withheld_approval_cannot_support_merge_ready(self):
        self.assertEqual(((9, "UNSUPPORTED_MERGE_READY"),),
                         self.findings((review(7), review(8, "CHANGES_REQUESTED"))))


if __name__ == "__main__":
    unittest.main()
