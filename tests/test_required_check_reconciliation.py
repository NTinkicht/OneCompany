"""OC-P0-01 (#365): fail-closed aggregation of required check runs on the exact head."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from live_work_reconciliation import (  # noqa: E402
    PullRequestObservation, WorkSnapshot, pr_inconsistencies,
)
from required_check_reconciliation import (  # noqa: E402
    CheckRunObservation, RequiredCheck, aggregate_required_checks,
)

MAIN = "a" * 40
HEAD = "c" * 40
OLD = "b" * 40
REQUIRED = (RequiredCheck("build", "github-actions"), RequiredCheck("tests", "github-actions"))


def run(id_, name, conclusion="success", *, status="completed", app="github-actions", head=HEAD):
    return CheckRunObservation(id_, name, app, head, status,
                               conclusion if status == "completed" else None)


GREEN = (run(1, "build"), run(2, "tests"))


class RequiredCheckAggregationTests(unittest.TestCase):
    def agg(self, runs, required=REQUIRED, head=HEAD):
        return aggregate_required_checks(required, runs, head)

    def test_all_required_checks_green_on_exact_head(self):
        result = self.agg(GREEN + (run(3, "optional-lint", "failure"),))
        self.assertEqual((HEAD, "success", ()), (result.ci_head_sha, result.ci_conclusion, result.findings))

    def test_missing_required_check_is_pending(self):
        result = self.agg((run(1, "build"),))
        self.assertEqual("pending", result.ci_conclusion)
        self.assertEqual((("tests", "MISSING_REQUIRED_CHECK"),), result.findings)

    def test_unfinished_required_check_is_pending(self):
        for status in ("queued", "in_progress", "waiting", "requested", "pending"):
            with self.subTest(status=status):
                result = self.agg((run(1, "build"), run(2, "tests", status=status)))
                self.assertEqual("pending", result.ci_conclusion)
                self.assertEqual((("tests", "PENDING_REQUIRED_CHECK"),), result.findings)

    def test_runs_on_another_head_never_count(self):
        result = self.agg((run(1, "build"), run(2, "tests", head=OLD)))
        self.assertEqual("pending", result.ci_conclusion)
        self.assertEqual((("tests", "MISSING_REQUIRED_CHECK"),), result.findings)

    def test_latest_rerun_wins_in_both_directions(self):
        failed_rerun = self.agg((run(1, "build"), run(2, "tests"), run(5, "tests", "failure")))
        self.assertEqual("failure", failed_rerun.ci_conclusion)
        self.assertEqual((("tests", "FAILED_REQUIRED_CHECK"),), failed_rerun.findings)
        # Input order is irrelevant: the highest id is the latest run.
        fixed_rerun = self.agg((run(9, "tests"), run(1, "build"), run(4, "tests", "failure")))
        self.assertEqual(("success", ()), (fixed_rerun.ci_conclusion, fixed_rerun.findings))
        pending_rerun = self.agg((run(1, "build"), run(2, "tests"), run(3, "tests", status="queued")))
        self.assertEqual("pending", pending_rerun.ci_conclusion)

    def test_only_success_passes(self):
        for conclusion in ("failure", "neutral", "skipped", "cancelled", "timed_out",
                           "action_required", "stale", "startup_failure", "SUCCESS"):
            with self.subTest(conclusion=conclusion):
                result = self.agg((run(1, "build"), run(2, "tests", conclusion)))
                self.assertEqual("failure", result.ci_conclusion)
                self.assertIn(("tests", "FAILED_REQUIRED_CHECK"), result.findings)

    def test_required_name_from_another_app_fails_closed(self):
        spoof = run(7, "tests", app="evil-app")
        result = self.agg(GREEN + (spoof,))
        self.assertEqual("failure", result.ci_conclusion)
        self.assertEqual((("tests", "FOREIGN_APP_CHECK"),), result.findings)
        alone = self.agg((run(1, "build"), spoof))
        self.assertEqual("failure", alone.ci_conclusion)
        self.assertEqual({("tests", "FOREIGN_APP_CHECK"), ("tests", "MISSING_REQUIRED_CHECK")},
                         set(alone.findings))
        # A foreign app on another head is not this head's evidence at all.
        self.assertEqual("success", self.agg(GREEN + (run(8, "tests", app="evil-app", head=OLD),)).ci_conclusion)

    def test_malformed_head_and_runs_fail_closed(self):
        for head in ("", "C" * 40, "c" * 39, None, 123):
            with self.subTest(head=head):
                result = self.agg(GREEN, head=head)
                self.assertEqual((None, "failure"), (result.ci_head_sha, result.ci_conclusion))
                self.assertIn(("", "INVALID_SHA"), result.findings)
        bad_runs = (
            CheckRunObservation(True, "tests", "github-actions", HEAD, "completed", "success"),
            CheckRunObservation(0, "tests", "github-actions", HEAD, "completed", "success"),
            CheckRunObservation(3, " tests", "github-actions", HEAD, "completed", "success"),
            CheckRunObservation(3, "tests", "", HEAD, "completed", "success"),
            CheckRunObservation(3, "tests", "github-actions", "C" * 40, "completed", "success"),
            CheckRunObservation(3, "tests", "github-actions", HEAD, "done", "success"),
            CheckRunObservation(3, "tests", "github-actions", HEAD, "completed", None),
            CheckRunObservation(3, "tests", "github-actions", HEAD, "queued", "success"),
            run(1, "tests"),  # duplicate id of GREEN[0]
        )
        for bad in bad_runs:
            with self.subTest(bad=bad):
                result = self.agg(GREEN + (bad,))
                self.assertEqual("failure", result.ci_conclusion)
                self.assertIn("INVALID_CHECK_RUN", {f for _, f in result.findings})
        self.assertEqual("failure", self.agg([run(1, "build"), run(2, "tests")]).ci_conclusion)

    def test_required_set_must_be_nonempty_and_well_formed(self):
        self.assertEqual((("", "NO_REQUIRED_CHECKS"),), self.agg(GREEN, required=()).findings)
        self.assertEqual("failure", self.agg(GREEN, required=()).ci_conclusion)
        for required in ((RequiredCheck("build", "github-actions"), RequiredCheck("build", "other")),
                         (RequiredCheck("", "github-actions"),), (RequiredCheck("build", " x"),),
                         ("build",), [RequiredCheck("build", "github-actions")]):
            with self.subTest(required=required):
                result = self.agg(GREEN, required=required)
                self.assertEqual("failure", result.ci_conclusion)
                self.assertIn(("", "INVALID_REQUIRED_CHECKS"), result.findings)

    def test_output_is_deterministic(self):
        runs = (run(4, "tests", "failure"), run(3, "build", status="queued"), run(9, "x", app="a"))
        first = self.agg(runs)
        self.assertEqual(first, self.agg(tuple(reversed(runs))))
        self.assertEqual(list(first.findings), sorted(first.findings))

    def test_aggregate_feeds_exact_head_pr_reconciliation(self):
        snapshot = WorkSnapshot(MAIN, MAIN, (7,), (), ((70, 7),), ())

        def observation(result):
            return PullRequestObservation(70, 7, HEAD, HEAD, MAIN, ci_head_sha=result.ci_head_sha,
                                          ci_base_sha=MAIN, ci_conclusion=result.ci_conclusion)

        self.assertEqual((), pr_inconsistencies(snapshot, (observation(self.agg(GREEN)),)))
        pending = observation(self.agg((run(1, "build"),)))
        self.assertEqual(((70, "CI_NOT_GREEN"),), pr_inconsistencies(snapshot, (pending,)))
        invalid = observation(self.agg(GREEN, head="bad"))
        self.assertEqual(((70, "STALE_CI"),), pr_inconsistencies(snapshot, (invalid,)))


if __name__ == "__main__":
    unittest.main()
