"""OC-P0-01 (#387): one captured raw-payload bundle -> the schema-5 snapshot."""
import contextlib
import copy
import datetime as dt
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from github_bundle_snapshot import InvalidBundle, main, snapshot_from_bundle  # noqa: E402
from github_pr_observation import pr_observation  # noqa: E402
from github_required_check_observation import required_check_observation  # noqa: E402
from github_snapshot_assembly import assemble_snapshot  # noqa: E402
from github_work_observation import work_observation  # noqa: E402
from live_reconciliation_report import build_report  # noqa: E402
from test_github_pr_observation import BOT, MAIN, NOW, inputs, pull  # noqa: E402
from test_github_snapshot_assembly import RULES  # noqa: E402
from test_github_work_observation import args as work_args, ref  # noqa: E402

AT = "2026-10-25T13:55:00+00:00"


def bundle():
    wa = work_args()
    pr = inputs()
    return {
        "observed_at": AT, "main_sha": MAIN, "active_lease_issue_ids": [1],
        "retired_pilot_issue_ids": [], "write_attempts": [], "trusted_reviewers": [BOT],
        "main_ref": ref(), "issue_pages": wa["issue_pages"], "issues_complete": wa["issues_complete"],
        "branch_pages": wa["branch_pages"], "branches_complete": wa["branches_complete"],
        "rule_pages": RULES, "rules_complete": True, "app_slugs": {"15368": "github-actions"},
        "pull_requests": [{
            "pull": pull(), "issue": pr["issue"], "recorded_head_sha": pr["recorded_head_sha"],
            "ci_base_sha": MAIN, "review_pages": pr["review_pages"], "reviews_complete": pr["reviews_complete"],
            "check_run_pages": pr["check_run_pages"], "check_runs_complete": pr["check_runs_complete"],
            "commit_pages": pr["commit_pages"], "commits_complete": pr["commits_complete"],
            "thread_pages": pr["thread_pages"]}],
    }


class BundleTests(unittest.TestCase):
    def test_equals_the_hand_assembled_document(self):
        pr = dict(pr_observation(pull(), **inputs()), ci_base_sha=MAIN)
        expected = assemble_snapshot(
            dt.datetime.fromisoformat(AT), work=work_observation(ref(), **work_args()),
            pull_requests=[pr],
            required_checks=required_check_observation(RULES, rules_complete=True, app_slugs={15368: "github-actions"}),
            main_sha=MAIN, active_lease_issue_ids=[1], trusted_reviewers=[BOT])
        self.assertEqual(expected, snapshot_from_bundle(bundle()))

    def test_end_to_end_report_is_consistent(self):
        self.assertEqual("CONSISTENT", build_report(snapshot_from_bundle(bundle()), NOW)["status"])

    def test_findings_still_reach_the_report(self):
        b = bundle()
        b["main_ref"] = ref("e" * 40)
        report = build_report(snapshot_from_bundle(b), NOW)
        self.assertEqual("INCONSISTENT", report["status"])

    def test_ci_base_sha_is_optional(self):
        b = bundle()
        del b["pull_requests"][0]["ci_base_sha"]
        self.assertNotIn("ci_base_sha", snapshot_from_bundle(b)["pull_requests"][0])

    def test_input_is_not_mutated(self):
        b = bundle()
        before = copy.deepcopy(b)
        snapshot_from_bundle(b)
        self.assertEqual(before, b)


class RefusalTests(unittest.TestCase):
    def refused(self, mutate):
        b = bundle()
        mutate(b)
        with self.assertRaises(InvalidBundle) as ctx:
            snapshot_from_bundle(b)
        return str(ctx.exception)

    def test_unknown_or_missing_keys(self):
        self.assertEqual("invalid bundle", self.refused(lambda b: b.update(extra=1)))
        self.assertEqual("invalid bundle", self.refused(lambda b: b.pop("rule_pages")))
        self.assertEqual("invalid pull_requests[0]", self.refused(lambda b: b["pull_requests"][0].pop("pull")))
        self.assertEqual("invalid pull_requests[0]", self.refused(lambda b: b["pull_requests"][0].update(x=1)))
        with self.assertRaises(InvalidBundle):
            snapshot_from_bundle([])

    def test_observed_at(self):
        for bad in ("2026-10-25T13:55:00", "yesterday", 5, None):
            self.assertEqual("invalid observed_at", self.refused(lambda b, v=bad: b.update(observed_at=v)))

    def test_app_slugs_keys_must_be_positive_decimal_strings(self):
        for bad in ({15368: "github-actions"}, {"abc": "x"}, {"-1": "x"}, {"0": "x"}, {"１５": "x"}, []):
            self.assertEqual("invalid app_slugs", self.refused(lambda b, v=bad: b.update(app_slugs=v)))

    def test_completeness_flags_must_be_real_booleans(self):
        for key in ("issues_complete", "branches_complete", "rules_complete"):
            self.assertEqual(f"invalid {key}", self.refused(lambda b, k=key: b.update({k: 1})))
        self.assertEqual("invalid pull_requests[0].reviews_complete",
                         self.refused(lambda b: b["pull_requests"][0].update(reviews_complete="yes")))

    def test_incomplete_listing_is_refused_not_partially_mapped(self):
        self.refused(lambda b: b.update(issues_complete=False))
        self.refused(lambda b: b.update(rules_complete=False))
        self.refused(lambda b: b["pull_requests"][0].update(commits_complete=False))

    def test_bad_ci_base_sha_and_pull_requests_container(self):
        self.assertEqual("invalid pull_requests[0].ci_base_sha",
                         self.refused(lambda b: b["pull_requests"][0].update(ci_base_sha="")))
        self.assertEqual("invalid pull_requests", self.refused(lambda b: b.update(pull_requests="x")))

    def test_duplicate_pull_request_is_refused(self):
        self.assertEqual("duplicate pull_requests[1].pr",
                         self.refused(lambda b: b["pull_requests"].append(copy.deepcopy(b["pull_requests"][0]))))

    def test_errors_never_echo_payload_values(self):
        secret = "ghp_SECRETVALUE0123456789"
        for mutate in (lambda b: b.update(main_sha=secret, observed_at=secret),
                       lambda b: b.update(app_slugs={secret: "x"}),
                       lambda b: b.update(trusted_reviewers=[secret, 1])):
            self.assertNotIn(secret, self.refused(mutate))


class CliTests(unittest.TestCase):
    def run_cli(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bundle.json"
            path.write_text(text, encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main([str(path)])
        return code, out.getvalue(), err.getvalue()

    def test_valid_bundle_prints_snapshot(self):
        code, out, _ = self.run_cli(json.dumps(bundle()))
        self.assertEqual(0, code)
        self.assertEqual(snapshot_from_bundle(bundle()), json.loads(out))

    def test_invalid_inputs_exit_2_with_no_stdout(self):
        for text in ("not json", "[]", json.dumps(dict(bundle(), extra=1))):
            code, out, err = self.run_cli(text)
            self.assertEqual((2, ""), (code, out))
            self.assertTrue(err.startswith("invalid bundle:"))

    def test_missing_file_exits_2(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(2, main(["/nonexistent/bundle.json"]))


if __name__ == "__main__":
    unittest.main()
