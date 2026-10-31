"""OC-P0-01 (#385): compose the GitHub mappers into the schema-5 snapshot."""
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from github_pr_observation import pr_observation  # noqa: E402
from github_required_check_observation import required_check_observation  # noqa: E402
from github_snapshot_assembly import InvalidAssembly, assemble_snapshot  # noqa: E402
from github_work_observation import work_observation  # noqa: E402
from live_reconciliation_report import build_report  # noqa: E402
from test_github_pr_observation import BOT, MAIN, NOW, inputs, pull  # noqa: E402
from test_github_work_observation import args as work_args, branch, issue, ref  # noqa: E402

AT = dt.datetime(2026, 10, 25, 13, 55, tzinfo=dt.timezone.utc)
RULES = [[{"type": "required_status_checks", "parameters": {"required_status_checks": [
    {"context": "validate", "integration_id": 15368},
    {"context": "lint", "integration_id": 15368}]}}]]


def parts(**over):
    kw = {
        "work": work_observation(ref(), **work_args()),
        # ci_base_sha is a claim the caller adds to the mapped record (#379).
        "pull_requests": [dict(pr_observation(pull(), **inputs()), ci_base_sha=MAIN)],
        "required_checks": required_check_observation(
            RULES, rules_complete=True, app_slugs={15368: "github-actions"}),
        "main_sha": MAIN,
        "active_lease_issue_ids": [1],
        "trusted_reviewers": [BOT],
    }
    kw.update(over)
    return kw


class AssemblyTests(unittest.TestCase):
    def test_exact_document_is_deterministic(self):
        doc = assemble_snapshot(AT, **parts())
        self.assertEqual(5, doc["schema_version"])
        self.assertEqual("2026-10-25T13:55:00+00:00", doc["observed_at"])
        self.assertEqual([[9, 1]], doc["snapshot"]["pr_issue_bindings"])
        self.assertEqual(["ai/1-feature", "main", "notes"], doc["branches"])
        self.assertEqual([2], doc["snapshot"]["next_ids"])
        self.assertEqual([4, 5], doc["snapshot"]["ineligible_issue_ids"])
        self.assertEqual([{"name": "lint", "app": "github-actions"},
                          {"name": "validate", "app": "github-actions"}],
                         doc["required_checks"])
        self.assertEqual(doc, assemble_snapshot(AT, **parts()))

    def test_end_to_end_report_is_consistent(self):
        doc = assemble_snapshot(AT, **parts())
        self.assertEqual("CONSISTENT", build_report(doc, NOW)["status"])

    def test_bindings_follow_pull_request_records_not_the_caller(self):
        record = dict(pr_observation(pull(), **inputs()), issue=2)
        doc = assemble_snapshot(AT, **parts(pull_requests=[record]))
        self.assertEqual([[9, 2]], doc["snapshot"]["pr_issue_bindings"])

    def test_findings_still_reach_the_report(self):
        stale = work_observation(ref("e" * 40), **work_args())
        blocked = work_args()
        blocked["issue_pages"][1][0] = issue(2, "l5:next", "l5:blocked")
        twin = work_args()
        twin["branch_pages"][1].append(branch("ai/1-other"))
        cases = {
            "stale main": (parts(work=stale), "snapshot"),
            "next also blocked": (parts(work=work_observation(ref(), **blocked)), "snapshot"),
            "duplicate stream": (parts(work=work_observation(ref(), **twin)), "branches"),
        }
        for name, (kw, section) in cases.items():
            with self.subTest(name):
                report = build_report(assemble_snapshot(AT, **kw), NOW)
                self.assertEqual("INCONSISTENT", report["status"])
                self.assertTrue(report["findings"][section])


class RefusalTests(unittest.TestCase):
    def refused(self, at=AT, **over):
        with self.assertRaises(InvalidAssembly) as ctx:
            assemble_snapshot(at, **parts(**over))
        return str(ctx.exception)

    def test_naive_or_non_datetime_observed_at(self):
        self.refused(at=AT.replace(tzinfo=None))
        self.refused(at="2026-10-25T13:55:00+00:00")

    def test_duplicate_pull_request_number(self):
        record = pr_observation(pull(), **inputs())
        self.assertEqual("duplicate pull_requests[1].pr",
                         self.refused(pull_requests=[record, dict(record)]))

    def test_malformed_pull_request_record(self):
        self.assertEqual("invalid pull_requests[0]", self.refused(pull_requests=["x"]))
        self.assertEqual("invalid pull_requests[0]", self.refused(pull_requests=[{"pr": True, "issue": 1}]))

    def test_work_must_be_the_exact_mapper_output(self):
        work = work_observation(ref(), **work_args())
        self.refused(work=dict(work, extra=1))
        self.refused(work={k: v for k, v in work.items() if k != "branches"})
        self.assertEqual("invalid work.next_ids", self.refused(work=dict(work, next_ids=[True])))
        self.refused(work=dict(work, branches="main"))

    def test_caller_records_are_type_checked(self):
        self.refused(active_lease_issue_ids=[True])
        self.refused(retired_pilot_issue_ids=["1"])
        self.refused(main_sha=None)
        self.refused(trusted_reviewers=[1])

    def test_bare_strings_are_never_sequences(self):
        for key in ("trusted_reviewers", "required_checks", "write_attempts"):
            with self.subTest(key):
                self.assertEqual(f"invalid {key}", self.refused(**{key: "ntk-reviewer"}))
        self.assertEqual("invalid active_lease_issue_ids", self.refused(active_lease_issue_ids="1"))

    def test_errors_never_echo_values(self):
        secret = "SECRET-VALUE-123"
        for over in ({"trusted_reviewers": [secret, 1]}, {"required_checks": [{"name": secret}]},
                     {"write_attempts": [{"operation_id": secret}]}):
            with self.subTest(over):
                self.assertNotIn(secret, self.refused(**over))


if __name__ == "__main__":
    unittest.main()
