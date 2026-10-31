"""OC-P0-01 (#363, #367, #371, #375): one fail-closed reconciliation report over a live snapshot."""
import copy
import contextlib
import datetime as dt
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from live_reconciliation_report import (  # noqa: E402
    EXIT_CONSISTENT, EXIT_INCONSISTENT, EXIT_INVALID, InvalidSnapshot,
    build_report, load_snapshot, main, render,
)

MAIN = "a" * 40
HEAD = "c" * 40
OLD_HEAD = "b" * 40
APP = "github-actions"


def run(run_id, name="validate", app=APP, head=HEAD, status="completed", conclusion="success"):
    return {"id": run_id, "name": name, "app": app, "head_sha": head,
            "status": status, "conclusion": conclusion}


BOT = "ntk-reviewer[bot]"


def marker(head=HEAD, mode="approve", base=MAIN, verdict="PASS"):
    base_part = f"base={base} " if base else ""
    return f"<!-- ntk-review v1 head={head} mode={mode} {base_part}verdict={verdict} floor=0 -->"


def review(review_id, reviewer=BOT, state="APPROVED", commit=HEAD, body=None):
    return {"id": review_id, "reviewer": reviewer, "state": state, "commit_id": commit,
            "body": f"PASS\n\n{marker()}" if body is None else body}


PARENT = "e" * 40


def commit(sha=HEAD, author="claude", committer="web-flow", message="Change\n\nMaterial-Author: claude"):
    return {"sha": sha, "author_login": author, "committer_login": committer, "message": message}


NOW = dt.datetime(2026, 10, 25, 14, 0, tzinfo=dt.timezone.utc)


def doc():
    """A fully consistent, fresh snapshot."""
    return {
        "schema_version": 4,
        "observed_at": "2026-10-25T13:55:00+00:00",
        "snapshot": {
            "main_sha": MAIN, "observed_main_sha": MAIN,
            "issue_ids": [1, 2, 3], "next_ids": [2],
            "pr_issue_bindings": [[9, 1]], "active_lease_issue_ids": [1],
            "retired_pilot_issue_ids": [], "ineligible_issue_ids": [],
        },
        "pull_requests": [{
            "pr": 9, "issue": 1, "recorded_head_sha": HEAD, "observed_head_sha": HEAD,
            "base_sha": MAIN, "ci_base_sha": MAIN,
            "check_runs": [run(11), run(12, name="lint")], "reviews": [review(21)],
            "commits": [commit(PARENT), commit()], "merge_ready_claimed": True,
        }],
        "branches": ["main", "ai/1-feature"],
        "write_attempts": [{"operation_id": "op-1", "issue": 1, "outcome": "success",
                            "readback": "present"}],
        "trusted_reviewers": ["ntk-reviewer[bot]"],
        "required_checks": [{"name": "validate", "app": APP}, {"name": "lint", "app": APP}],
    }


class ReportTests(unittest.TestCase):
    def test_consistent_snapshot_carries_sha_and_timestamps(self):
        report = build_report(doc(), NOW)
        self.assertEqual("CONSISTENT", report["status"])
        self.assertEqual(MAIN, report["main_sha"])
        self.assertEqual(MAIN, report["observed_main_sha"])
        self.assertEqual("2026-10-25T13:55:00+00:00", report["observed_at"])
        self.assertEqual("2026-10-25T14:00:00+00:00", report["checked_at"])
        self.assertTrue(all(v == [] for v in report["findings"].values()))

    def test_every_check_surfaces_and_fails_closed(self):
        cases = {
            "snapshot": (lambda d: d["snapshot"].update(next_ids=[1]), "ACTIVE_WORK_IN_NEXT"),
            "freshness": (lambda d: d.update(observed_at="2026-10-25T13:00:00+00:00"), "STALE_SNAPSHOT"),
            "pull_requests": (lambda d: d["pull_requests"][0].update(commits=[commit(author=BOT)]),
                              [9, "UNTRUSTED_APPROVAL"]),
            "reviews": (lambda d: d["pull_requests"][0].update(reviews=[review(21, commit=OLD_HEAD)]),
                        [9, "", "STALE_HEAD_APPROVAL"]),
            "branches": (lambda d: d["branches"].append("ai/1-other"), ["ai/1-other", "DUPLICATE_STREAM"]),
            "write_attempts": (lambda d: d["write_attempts"][0].update(outcome="unknown", readback=None),
                               ["op-1", "UNVERIFIED_OUTCOME"]),
        }
        for check, (mutate, finding) in cases.items():
            with self.subTest(check=check):
                data = doc()
                mutate(data)
                report = build_report(data, NOW)
                self.assertEqual("INCONSISTENT", report["status"])
                self.assertIn(finding, report["findings"][check])

    def test_future_snapshot_and_bad_max_age_are_inconsistent(self):
        data = doc()
        data["observed_at"] = "2026-10-25T14:00:01+00:00"
        self.assertEqual(["FUTURE_SNAPSHOT"], build_report(data, NOW)["findings"]["freshness"])
        self.assertIn("INVALID_MAX_AGE", build_report(doc(), NOW, 0)["findings"]["freshness"])
        self.assertEqual("INCONSISTENT", build_report(doc(), NOW, 0)["status"])

    def test_unobserved_binding_is_reported_without_any_pr_observation(self):
        data = doc()
        data["pull_requests"] = []
        self.assertEqual([[9, "UNOBSERVED_PR_BINDING"]],
                         build_report(data, NOW)["findings"]["pull_requests"])

    def test_output_is_deterministic(self):
        self.assertEqual(render(build_report(doc(), NOW)), render(build_report(copy.deepcopy(doc()), NOW)))


class RequiredCheckTests(unittest.TestCase):
    """#367: each PR's CI comes only from exact-head required check runs."""

    def report_with(self, runs, merge_ready=True):
        data = doc()
        data["pull_requests"][0]["check_runs"] = runs
        data["pull_requests"][0]["merge_ready_claimed"] = merge_ready
        return build_report(data, NOW)

    def test_green_required_checks_are_consistent(self):
        report = build_report(doc(), NOW)
        self.assertEqual("CONSISTENT", report["status"])
        self.assertEqual([], report["findings"]["required_checks"])

    def test_unproven_ci_is_inconsistent_with_both_findings(self):
        lint = run(12, name="lint")
        cases = {
            "missing": ([run(11)], "MISSING_REQUIRED_CHECK", "lint"),
            "pending": ([run(11), run(12, name="lint", status="in_progress", conclusion=None)],
                        "PENDING_REQUIRED_CHECK", "lint"),
            "failed rerun": ([run(11), lint, run(13, conclusion="failure")],
                             "FAILED_REQUIRED_CHECK", "validate"),
            "neutral": ([run(11, conclusion="neutral"), lint], "FAILED_REQUIRED_CHECK", "validate"),
            "stale head only": ([run(11, head=OLD_HEAD), lint], "MISSING_REQUIRED_CHECK", "validate"),
            "foreign app": ([run(11), lint, run(14, app="evil-app")], "FOREIGN_APP_CHECK", "validate"),
        }
        for label, (runs, finding, check) in cases.items():
            with self.subTest(case=label):
                report = self.report_with(runs)
                self.assertEqual("INCONSISTENT", report["status"])
                self.assertIn([9, check, finding], report["findings"]["required_checks"])
                self.assertIn([9, "CI_NOT_GREEN"], report["findings"]["pull_requests"])
                self.assertIn([9, "UNSUPPORTED_MERGE_READY"], report["findings"]["pull_requests"])

    def test_success_rerun_after_failure_is_green(self):
        runs = [run(11, conclusion="failure"), run(15), run(12, name="lint")]
        self.assertEqual("CONSISTENT", self.report_with(runs)["status"])

    def test_no_required_checks_never_proves_ci(self):
        data = doc()
        data["required_checks"] = []
        report = build_report(data, NOW)
        self.assertEqual("INCONSISTENT", report["status"])
        self.assertIn([9, "", "NO_REQUIRED_CHECKS"], report["findings"]["required_checks"])
        self.assertIn([9, "CI_NOT_GREEN"], report["findings"]["pull_requests"])

    def test_invalid_check_run_values_fail_closed(self):
        report = self.report_with([run(11, status="done"), run(12, name="lint")])
        self.assertIn([9, "validate", "INVALID_CHECK_RUN"], report["findings"]["required_checks"])
        self.assertEqual("INCONSISTENT", report["status"])


class ReviewAttributionTests(unittest.TestCase):
    """#371: each PR's approval comes only from exact-head trusted reviews."""

    def report_with(self, reviews, **pr_updates):
        data = doc()
        data["pull_requests"][0]["reviews"] = reviews
        data["pull_requests"][0].update(pr_updates)
        return build_report(data, NOW)

    def test_marker_bearing_exact_head_approval_is_consistent(self):
        report = build_report(doc(), NOW)
        self.assertEqual("CONSISTENT", report["status"])
        self.assertEqual([], report["findings"]["reviews"])

    def test_unproven_approval_is_inconsistent_with_both_findings(self):
        cases = {
            "no reviews": ([], None),
            "stale head": ([review(21, commit=OLD_HEAD)], [9, "", "STALE_HEAD_APPROVAL"]),
            "changes requested latest": ([review(21), review(22, state="CHANGES_REQUESTED", body="")],
                                         [9, "22", "CHANGES_REQUESTED"]),
            "dismissed only": ([review(21, state="DISMISSED")], None),
            "commented only": ([review(21, state="COMMENTED")], None),
            "markerless": ([review(21, body="LGTM")], [9, "21", "INVALID_APPROVAL_MARKER"]),
            "echoed marker": ([review(21, body=marker() + marker())], [9, "21", "INVALID_APPROVAL_MARKER"]),
            "comment mode": ([review(21, body=marker(mode="comment"))], [9, "21", "MARKER_NOT_APPROVE_MODE"]),
            "not pass": ([review(21, body=marker(verdict="CHANGES_REQUIRED"))],
                         [9, "21", "MARKER_VERDICT_NOT_PASS"]),
            "no base": ([review(21, body=marker(base=None))], [9, "21", "APPROVAL_WITHOUT_BASE"]),
            "marker for other head": ([review(21, body=marker(head=OLD_HEAD))],
                                      [9, "21", "MARKER_HEAD_MISMATCH"]),
            "untrusted reviewer": ([review(21, reviewer="someone")], [9, "21", "UNTRUSTED_REVIEWER_APPROVAL"]),
            "trusted login case variant": ([review(21, reviewer="NTK-reviewer[bot]")],
                                           [9, "21", "UNTRUSTED_REVIEWER_APPROVAL"]),
            "duplicate review id": ([review(21), review(21)], [9, "21", "INVALID_REVIEW"]),
            "unknown state": ([review(21, state="PENDING")], [9, "21", "INVALID_REVIEW"]),
        }
        for label, (reviews, finding) in cases.items():
            with self.subTest(case=label):
                report = self.report_with(reviews)
                self.assertEqual("INCONSISTENT", report["status"])
                if finding is not None:
                    self.assertIn(finding, report["findings"]["reviews"])
                self.assertIn([9, "UNSUPPORTED_MERGE_READY"], report["findings"]["pull_requests"])

    def test_later_approval_supersedes_changes_requested(self):
        reviews = [review(20, state="CHANGES_REQUESTED", body=""), review(21)]
        self.assertEqual("CONSISTENT", self.report_with(reviews)["status"])

    def test_empty_trusted_reviewer_list_never_attributes_an_approval(self):
        data = doc()
        data["trusted_reviewers"] = []
        report = build_report(data, NOW)
        self.assertEqual("INCONSISTENT", report["status"])
        self.assertIn([9, "", "INVALID_TRUSTED_REVIEWERS"], report["findings"]["reviews"])
        self.assertIn([9, "UNSUPPORTED_MERGE_READY"], report["findings"]["pull_requests"])

    def test_derived_approval_still_needs_independence_and_a_fresh_base(self):
        self_approved = self.report_with([review(21)], commits=[commit(author=BOT)])
        self.assertIn([9, "UNTRUSTED_APPROVAL"], self_approved["findings"]["pull_requests"])
        self.assertEqual([], self_approved["findings"]["reviews"])
        old_base = "d" * 40
        stale_base = self.report_with([review(21, body=marker(base=old_base))])
        self.assertEqual("INCONSISTENT", stale_base["status"])
        self.assertEqual([], stale_base["findings"]["reviews"])
        self.assertEqual([[9, "STALE_APPROVAL"], [9, "UNSUPPORTED_MERGE_READY"]],
                         stale_base["findings"]["pull_requests"])


class MaterialAuthorshipTests(unittest.TestCase):
    """#375: each PR's material authors come only from its exact-head commit list."""

    def report_with(self, commits):
        data = doc()
        data["pull_requests"][0]["commits"] = commits
        return build_report(data, NOW)

    def test_independent_commit_list_is_consistent(self):
        report = build_report(doc(), NOW)
        self.assertEqual("CONSISTENT", report["status"])
        self.assertEqual([], report["findings"]["commits"])

    def test_approver_in_any_authorship_role_is_untrusted(self):
        cases = {
            "head author": [commit(PARENT), commit(author=BOT)],
            "earlier author": [commit(PARENT, author=BOT), commit()],
            "committer": [commit(PARENT), commit(committer=BOT)],
            "trailer": [commit(PARENT), commit(message=f"Fix\n\nMaterial-Author: {BOT}")],
            "case variant": [commit(PARENT), commit(author="NTK-Reviewer[bot]")],
        }
        for label, commits in cases.items():
            with self.subTest(case=label):
                report = self.report_with(commits)
                self.assertEqual("INCONSISTENT", report["status"])
                self.assertEqual([], report["findings"]["commits"])
                self.assertIn([9, "UNTRUSTED_APPROVAL"], report["findings"]["pull_requests"])

    def test_ambiguous_authorship_is_withheld_and_never_independence(self):
        many = [commit(f"{i:040x}") for i in range(1, 250)] + [commit()]
        cases = {
            "no commits": ([], [9, "", "NO_COMMITS"]),
            "head not last": ([commit(), commit(PARENT)], [9, "", "HEAD_NOT_LAST_COMMIT"]),
            "stale head only": ([commit(OLD_HEAD)], [9, "", "HEAD_NOT_LAST_COMMIT"]),
            "unlinked author": ([commit(PARENT, author=None), commit()],
                                [9, PARENT, "UNATTRIBUTED_COMMIT"]),
            "blank committer": ([commit(committer=" ")], [9, HEAD, "UNATTRIBUTED_COMMIT"]),
            "empty trailer": ([commit(message="x\n\nMaterial-Author:   ")],
                              [9, HEAD, "INVALID_MATERIAL_AUTHOR_TRAILER"]),
            "duplicate": ([commit(PARENT), commit(PARENT), commit()], [9, PARENT, "DUPLICATE_COMMIT"]),
            "malformed sha": ([commit("not-a-sha"), commit()], [9, "", "INVALID_COMMIT"]),
            "truncated": (many, [9, "", "COMMIT_LIST_TRUNCATED"]),
        }
        for label, (commits, finding) in cases.items():
            with self.subTest(case=label):
                report = self.report_with(commits)
                self.assertEqual("INCONSISTENT", report["status"])
                self.assertIn(finding, report["findings"]["commits"])
                self.assertIn([9, "UNTRUSTED_APPROVAL"], report["findings"]["pull_requests"])
                self.assertIn([9, "UNSUPPORTED_MERGE_READY"], report["findings"]["pull_requests"])

    def test_commit_findings_are_sorted_and_deterministic(self):
        commits = [commit(PARENT, author=None), commit(MAIN, committer=None), commit()]
        report = self.report_with(commits)
        self.assertEqual([[9, MAIN, "UNATTRIBUTED_COMMIT"], [9, PARENT, "UNATTRIBUTED_COMMIT"]],
                         report["findings"]["commits"])


class LoaderTests(unittest.TestCase):
    def test_strict_loader_refuses_malformed_input(self):
        mutations = [
            lambda d: d.pop("branches"),
            lambda d: d.update(extra=1),
            lambda d: d.update(schema_version=2),
            lambda d: d.update(schema_version=3),
            lambda d: d.update(schema_version=5),
            lambda d: d.update(schema_version=True),
            lambda d: d.update(observed_at="2026-10-25T13:55:00"),  # naive
            lambda d: d.update(observed_at="yesterday"),
            lambda d: d.update(observed_at=1761400500),
            lambda d: d["snapshot"].update(issue_ids=[1, True]),
            lambda d: d["snapshot"].update(next_ids=[2.0]),
            lambda d: d["snapshot"].update(pr_issue_bindings=[[9]]),
            lambda d: d["snapshot"].update(unknown=[]),
            lambda d: d["snapshot"].pop("main_sha"),
            lambda d: d["pull_requests"][0].update(pr="9"),
            lambda d: d["pull_requests"][0].update(merge_ready_claimed="yes"),
            # #375: material authorship is derived from commits, never caller-asserted.
            lambda d: d["pull_requests"][0].update(material_authors=["claude"]),
            lambda d: d["pull_requests"][0].pop("commits"),
            lambda d: d["pull_requests"][0].update(commits={}),
            lambda d: d["pull_requests"][0]["commits"][0].pop("author_login"),
            lambda d: d["pull_requests"][0]["commits"][0].update(author_login=7),
            lambda d: d["pull_requests"][0]["commits"][0].update(sha=None),
            lambda d: d["pull_requests"][0]["commits"][0].update(message=None),
            lambda d: d["pull_requests"][0]["commits"][0].update(extra=1),
            lambda d: d["pull_requests"][0].pop("base_sha"),
            lambda d: d.update(pull_requests={}),
            lambda d: d["write_attempts"][0].update(retries=False),
            lambda d: d["write_attempts"][0].update(safety_rejected=1),
            lambda d: d.update(branches="ai/1-feature"),
            lambda d: d.update(trusted_reviewers=[None]),
            # #367: CI is derived, never caller-asserted.
            lambda d: d["pull_requests"][0].update(ci_conclusion="success"),
            lambda d: d["pull_requests"][0].update(ci_head_sha=HEAD),
            lambda d: d["pull_requests"][0].pop("check_runs"),
            lambda d: d["pull_requests"][0].update(check_runs={}),
            lambda d: d["pull_requests"][0]["check_runs"][0].update(id=True),
            lambda d: d["pull_requests"][0]["check_runs"][0].update(id="11"),
            lambda d: d["pull_requests"][0]["check_runs"][0].pop("conclusion"),
            lambda d: d["pull_requests"][0]["check_runs"][0].update(extra=1),
            lambda d: d["pull_requests"][0]["check_runs"][0].update(head_sha=None),
            lambda d: d.pop("required_checks"),
            lambda d: d.update(required_checks=[{"name": "validate"}]),
            lambda d: d.update(required_checks=[{"name": "validate", "app": APP, "x": 1}]),
            lambda d: d.update(required_checks=[["validate", APP]]),
            # #371: the approval is derived from reviews, never caller-asserted.
            lambda d: d["pull_requests"][0].update(approved_by=BOT),
            lambda d: d["pull_requests"][0].update(approved_head_sha=HEAD),
            lambda d: d["pull_requests"][0].update(approved_base_sha=MAIN),
            lambda d: d["pull_requests"][0].pop("reviews"),
            lambda d: d["pull_requests"][0].update(reviews={}),
            lambda d: d["pull_requests"][0]["reviews"][0].update(id=True),
            lambda d: d["pull_requests"][0]["reviews"][0].update(id="21"),
            lambda d: d["pull_requests"][0]["reviews"][0].pop("body"),
            lambda d: d["pull_requests"][0]["reviews"][0].update(body=None),
            lambda d: d["pull_requests"][0]["reviews"][0].update(commit_id=None),
            lambda d: d["pull_requests"][0]["reviews"][0].update(extra=1),
        ]
        for i, mutate in enumerate(mutations):
            with self.subTest(case=i):
                data = doc()
                mutate(data)
                with self.assertRaises(InvalidSnapshot):
                    load_snapshot(data)
        with self.assertRaises(InvalidSnapshot):
            load_snapshot([])

    def test_error_names_the_schema_path_not_the_value(self):
        data = doc()
        data["snapshot"]["main_sha"] = 12345678
        with self.assertRaises(InvalidSnapshot) as ctx:
            load_snapshot(data)
        self.assertEqual("invalid snapshot.main_sha", str(ctx.exception))

    def test_optional_snapshot_lists_default_empty(self):
        data = doc()
        del data["snapshot"]["retired_pilot_issue_ids"], data["snapshot"]["ineligible_issue_ids"]
        self.assertEqual("CONSISTENT", build_report(data, NOW)["status"])


class CliTests(unittest.TestCase):
    def run_cli(self, text, *extra):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snapshot.json"
            path.write_text(text, encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = main([str(path), *extra], now=NOW)
        return code, out.getvalue(), err.getvalue()

    def test_exit_codes(self):
        code, out, _ = self.run_cli(json.dumps(doc()))
        self.assertEqual(EXIT_CONSISTENT, code)
        self.assertEqual("CONSISTENT", json.loads(out)["status"])

        stale = doc()
        stale["observed_at"] = "2026-10-25T13:00:00+00:00"
        code, out, _ = self.run_cli(json.dumps(stale))
        self.assertEqual(EXIT_INCONSISTENT, code)
        self.assertEqual(EXIT_CONSISTENT, self.run_cli(json.dumps(stale), "--max-age-seconds", "3600")[0])

        for text in ["{not json", "[]", json.dumps({**doc(), "schema_version": 3})]:
            code, out, err = self.run_cli(text)
            self.assertEqual((EXIT_INVALID, ""), (code, out))
            self.assertTrue(err.startswith("invalid snapshot:"))

    def test_missing_file_is_invalid(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(EXIT_INVALID, main(["/nonexistent/snapshot.json"], now=NOW))


if __name__ == "__main__":
    unittest.main()
