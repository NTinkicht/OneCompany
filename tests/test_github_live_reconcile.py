"""OC-P0-01 (#397): the live reconcile runner chains capture, snapshot and verdict fail-closed."""
import copy
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from github_bundle_snapshot import snapshot_from_bundle  # noqa: E402
from github_live_reconcile import LiveReconciliationRefused, reconcile_live  # noqa: E402
from github_page_capture import CaptureError, Response  # noqa: E402
from live_reconciliation_report import build_report  # noqa: E402
from test_github_bundle_capture import REPO, SECRET, Server, caller_fields, pull_spec  # noqa: E402
from test_github_bundle_snapshot import bundle  # noqa: E402
from test_github_pr_observation import NOW  # noqa: E402


def run(server=None, **overrides):
    fields = {**caller_fields(), "now": NOW, "pulls": [pull_spec()]}
    fields.update(overrides)
    pulls = fields.pop("pulls")
    return reconcile_live(server or Server(), REPO, pulls, **fields)


class LiveReconcileTests(unittest.TestCase):
    def test_verdict_equals_the_reference_pipeline(self):
        expected = build_report(snapshot_from_bundle(bundle()), NOW)
        self.assertEqual(expected, run())

    def test_stale_observed_at_is_inconsistent_with_a_freshness_finding(self):
        report = run(now=NOW + dt.timedelta(hours=2))
        self.assertEqual("INCONSISTENT", report["status"])
        self.assertTrue(report["findings"]["freshness"])

    def test_max_age_is_passed_through(self):
        report = run(max_age_seconds=1)
        self.assertEqual(1, report["max_age_seconds"])

    def test_main_moving_during_capture_is_refused_not_reported(self):
        moved = copy.deepcopy(bundle()["main_ref"])
        moved["object"]["sha"] = "f" * 40
        with self.assertRaises(LiveReconciliationRefused) as ctx:
            run(Server(refs=[bundle()["main_ref"], moved]))
        self.assertEqual("capture refused", str(ctx.exception))

    def test_malformed_baseline_is_refused_by_step(self):
        with self.assertRaises(LiveReconciliationRefused) as ctx:
            run(observed_at="not-a-time")
        self.assertIn("bundle refused", str(ctx.exception))

    def test_invalid_pull_specs_are_refused_by_step(self):
        with self.assertRaises(LiveReconciliationRefused) as ctx:
            run(pulls="x")
        self.assertIn("capture refused", str(ctx.exception))

    def test_malformed_baseline_containers_are_refused(self):
        for key in ("active_lease_issue_ids", "retired_pilot_issue_ids", "write_attempts",
                    "trusted_reviewers", "app_slugs"):
            with self.subTest(key=key), self.assertRaises(LiveReconciliationRefused):
                run(**{key: None})

    def test_raising_fetchers_are_normalized_without_leaking_text(self):
        for exc in (CaptureError(SECRET), OSError(SECRET), TimeoutError(SECRET)):
            def raising(path, exc=exc):
                raise exc
            with self.subTest(exc=type(exc).__name__), self.assertRaises(LiveReconciliationRefused) as ctx:
                run(raising)
            self.assertEqual("capture refused", str(ctx.exception))

    def test_naive_or_non_datetime_now_is_refused(self):
        for bad in (dt.datetime(2026, 10, 25, 14, 0), "2026-10-25T14:00:00+00:00", None):
            with self.subTest(bad=bad), self.assertRaises(LiveReconciliationRefused):
                run(now=bad)

    def test_transport_failure_is_refused_without_leaking_the_body(self):
        def failing(path):
            return Response(500, {"message": SECRET}, None)
        with self.assertRaises(LiveReconciliationRefused) as ctx:
            run(failing)
        self.assertNotIn(SECRET, str(ctx.exception))

    def test_caller_inputs_are_not_mutated(self):
        fields = {**caller_fields(), "now": NOW}
        pulls = [pull_spec()]
        before = copy.deepcopy((fields, pulls))
        reconcile_live(Server(), REPO, pulls, **fields)
        self.assertEqual(before, (fields, pulls))


if __name__ == "__main__":
    unittest.main()
