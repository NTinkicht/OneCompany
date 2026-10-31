"""OC-P0-01 (#381): raw GitHub issue/branch/main-ref payloads -> snapshot work fields."""
import copy
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # shared #379 fixtures

from github_pr_observation import pr_observation  # noqa: E402
from github_work_observation import InvalidPayload, work_observation  # noqa: E402
from live_reconciliation_report import build_report, load_snapshot  # noqa: E402
from test_github_pr_observation import BOT, MAIN, NOW, inputs, pull  # noqa: E402

OTHER = "f" * 40


def ref(sha=MAIN, name="refs/heads/main", kind="commit"):
    return {"ref": name, "node_id": "x", "url": "x",
            "object": {"sha": sha, "type": kind, "url": "x"}}


def issue(number, *labels, state="open"):
    return {"number": number, "state": state, "title": "ignored",
            "labels": [{"id": 7, "name": name, "color": "fff"} for name in labels],
            "user": {"login": "NTinkicht"}}


def pr_item(number):
    return dict(issue(number), pull_request={"url": "x", "merged_at": None})


def branch(name):
    return {"name": name, "commit": {"sha": MAIN, "url": "x"}, "protected": name == "main"}


def args():
    return {
        "issue_pages": [[issue(3, "bug"), pr_item(9), issue(1)],
                        [issue(2, "l5:next"), issue(4, "l5:parked"), issue(5, "l5:owner")]],
        "issues_complete": True,
        "branch_pages": [[branch("main"), branch("ai/1-feature")], [branch("notes")]],
        "branches_complete": True,
    }


def document(work, record):
    return {
        "schema_version": 5,
        "observed_at": "2026-10-25T13:55:00+00:00",
        "snapshot": {
            "main_sha": MAIN, "observed_main_sha": work["observed_main_sha"],
            "issue_ids": work["issue_ids"], "next_ids": work["next_ids"],
            "pr_issue_bindings": [[9, 1]], "active_lease_issue_ids": [1],
            "retired_pilot_issue_ids": [],
            "ineligible_issue_ids": work["ineligible_issue_ids"],
        },
        "pull_requests": [dict(record, ci_base_sha=MAIN, merge_ready_claimed=True)],
        "branches": work["branches"],
        "write_attempts": [],
        "trusted_reviewers": [BOT],
        "required_checks": [{"name": "validate", "app": "github-actions"},
                            {"name": "lint", "app": "github-actions"}],
    }


class MappingTests(unittest.TestCase):
    def test_maps_exact_fields_deterministically(self):
        work = work_observation(ref(), **args())
        self.assertEqual({
            "observed_main_sha": MAIN,
            "issue_ids": [1, 2, 3, 4, 5],
            "next_ids": [2],
            "ineligible_issue_ids": [4, 5],
            "branches": ["ai/1-feature", "main", "notes"],
        }, work)
        self.assertEqual(work, work_observation(ref(), **args()))

    def test_pull_requests_are_never_issues(self):
        a = args()
        a["issue_pages"] = [[pr_item(9), dict(pr_item(10), labels=[{"name": "l5:next"}])]]
        work = work_observation(ref(), **a)
        self.assertEqual(([], [], []),
                         (work["issue_ids"], work["next_ids"], work["ineligible_issue_ids"]))

    def test_end_to_end_report_is_consistent(self):
        data = document(work_observation(ref(), **args()), pr_observation(pull(), **inputs()))
        load_snapshot(data)
        self.assertEqual("CONSISTENT", build_report(data, NOW)["status"])

    def test_findings_still_reach_the_report(self):
        cases = {
            "NEXT that is also blocked": (
                lambda a: a["issue_pages"][1].__setitem__(0, issue(2, "l5:next", "l5:blocked")),
                ref(), "snapshot", ["INELIGIBLE_NEXT"]),
            "two streams for one issue": (
                lambda a: a["branch_pages"][1].append(branch("ai/1-other")),
                ref(), "branches",
                [["ai/1-feature", "DUPLICATE_STREAM"], ["ai/1-other", "DUPLICATE_STREAM"]]),
            "branch for an issue that is not open": (
                lambda a: a["branch_pages"][1].append(branch("ai/8-gone")),
                ref(), "branches", [["ai/8-gone", "ORPHAN_BRANCH"]]),
            "main moved since it was recorded": (
                lambda a: None, ref(OTHER), "snapshot", ["STALE_MAIN"]),
        }
        record = pr_observation(pull(), **inputs())
        for label, (mutate, main_ref, section, expected) in cases.items():
            with self.subTest(label):
                a = copy.deepcopy(args())
                mutate(a)
                report = build_report(document(work_observation(main_ref, **a), record), NOW)
                self.assertEqual("INCONSISTENT", report["status"])
                self.assertEqual(expected, report["findings"][section])

    def test_refuses_malformed_or_incomplete_payloads(self):
        def with_issue(item):
            return lambda a: a.__setitem__("issue_pages", [[item]])

        def with_branch(item):
            return lambda a: a.__setitem__("branch_pages", [[item]])

        cases = {
            "issues not paged to the end": (lambda a: a.update(issues_complete=False), ref()),
            "branches not paged to the end": (lambda a: a.update(branches_complete=False), ref()),
            "truthy completeness": (lambda a: a.update(issues_complete=1), ref()),
            "page not a list": (lambda a: a.__setitem__("issue_pages", [{"items": []}]), ref()),
            "closed issue": (with_issue(issue(1, state="closed")), ref()),
            "boolean number": (with_issue(dict(issue(1), number=True)), ref()),
            "zero number": (with_issue(issue(0)), ref()),
            "string number": (with_issue(dict(issue(1), number="1")), ref()),
            "missing labels": (with_issue({"number": 1, "state": "open"}), ref()),
            "label without a name": (with_issue(dict(issue(1), labels=[{"id": 1}])), ref()),
            "label as a plain string": (with_issue(dict(issue(1), labels=["l5:next"])), ref()),
            "non-object item": (with_issue(1), ref()),
            "duplicate issue": (
                lambda a: a.__setitem__("issue_pages", [[issue(1)], [issue(1, "l5:next")]]), ref()),
            "duplicate branch": (
                lambda a: a.__setitem__("branch_pages", [[branch("main")], [branch("main")]]), ref()),
            "branch without a name": (with_branch({"commit": {}}), ref()),
            "empty branch name": (with_branch(branch("")), ref()),
            "ref of another branch": (lambda a: None, ref(name="refs/heads/dev")),
            "ref to a tag object": (lambda a: None, ref(kind="tag")),
            "ref without a sha": (lambda a: None, {"ref": "refs/heads/main", "object": {"type": "commit"}}),
            "ref list (ambiguous match)": (lambda a: None, [ref()]),
        }
        for label, (mutate, main_ref) in cases.items():
            with self.subTest(label):
                a = copy.deepcopy(args())
                mutate(a)
                with self.assertRaises(InvalidPayload):
                    work_observation(main_ref, **a)

    def test_error_names_path_not_value(self):
        secret = "ghp_" + "x" * 36
        a = args()
        a["issue_pages"] = [[dict(issue(1), state=secret)]]
        with self.assertRaises(InvalidPayload) as caught:
            work_observation(ref(), **a)
        self.assertEqual("invalid issues[0].state", str(caught.exception))
        a = args()
        a["branch_pages"] = [[{"name": 5, "commit": secret}]]
        with self.assertRaises(InvalidPayload) as caught:
            work_observation(ref(), **a)
        self.assertNotIn(secret, str(caught.exception))
        self.assertEqual("invalid branches[0].name", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
