"""OC-P0-01 (#379): raw GitHub payloads -> one schema-5 PR observation, fail closed."""
import copy
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from github_pr_observation import InvalidPayload, pr_observation  # noqa: E402
from live_reconciliation_report import build_report, load_snapshot  # noqa: E402

MAIN = "a" * 40
HEAD = "c" * 40
PARENT = "e" * 40
OTHER = "f" * 40
BOT = "ntk-reviewer[bot]"
NOW = dt.datetime(2026, 10, 25, 14, 0, tzinfo=dt.timezone.utc)


def marker():
    return (f"<!-- ntk-review v1 head={HEAD} mode=approve base={MAIN} "
            "verdict=PASS floor=0 -->")


def pull():
    return {"number": 9, "title": "ignored", "head": {"sha": HEAD, "ref": "ai/1-x"},
            "base": {"sha": MAIN, "ref": "main"}, "user": {"login": "NTinkicht"}}


def gh_review(review_id=21, login=BOT, commit=HEAD, state="APPROVED"):
    return {"id": review_id, "user": {"login": login, "type": "Bot"}, "state": state,
            "commit_id": commit, "body": f"PASS\n\n{marker()}", "html_url": "x"}


def gh_run(run_id, name, head=HEAD, slug="github-actions"):
    return {"id": run_id, "name": name, "head_sha": head, "status": "completed",
            "conclusion": "success", "app": {"slug": slug, "id": 15368}}


def gh_commit(sha, author="claude", message="Change\n\nMaterial-Author: claude"):
    return {"sha": sha, "author": None if author is None else {"login": author},
            "committer": {"login": "web-flow"}, "commit": {"message": message}}


def thread_page(nodes, has_next=False):
    return {"nodes": nodes, "pageInfo": {"hasNextPage": has_next, "endCursor": "c"}}


def node(thread_id, resolved=True, outdated=False):
    return {"id": thread_id, "isResolved": resolved, "isOutdated": outdated}


def inputs():
    return {
        "issue": 1,
        "recorded_head_sha": HEAD,
        "review_pages": [[gh_review()]],
        "reviews_complete": True,
        "check_run_pages": [
            {"total_count": 2, "check_runs": [gh_run(12, "lint")]},
            {"total_count": 2, "check_runs": [gh_run(11, "validate")]},
        ],
        "check_runs_complete": True,
        "commit_pages": [[gh_commit(PARENT)], [gh_commit(HEAD)]],
        "commits_complete": True,
        "thread_pages": [thread_page([node("PRRT_2", outdated=True)], has_next=True),
                         thread_page([node("PRRT_1")])],
    }


def snapshot(record):
    return {
        "schema_version": 5,
        "observed_at": "2026-10-25T13:55:00+00:00",
        "snapshot": {
            "main_sha": MAIN, "observed_main_sha": MAIN,
            "issue_ids": [1, 2, 3], "next_ids": [2],
            "pr_issue_bindings": [[9, 1]], "active_lease_issue_ids": [1],
            "retired_pilot_issue_ids": [], "ineligible_issue_ids": [],
        },
        "pull_requests": [dict(record, ci_base_sha=MAIN, merge_ready_claimed=True)],
        "branches": ["main", "ai/1-feature"],
        "write_attempts": [],
        "trusted_reviewers": [BOT],
        "required_checks": [{"name": "validate", "app": "github-actions"},
                            {"name": "lint", "app": "github-actions"}],
    }


class MappingTests(unittest.TestCase):
    def test_maps_exact_fields_deterministically(self):
        record = pr_observation(pull(), **inputs())
        self.assertEqual({
            "pr": 9, "issue": 1, "recorded_head_sha": HEAD, "observed_head_sha": HEAD,
            "base_sha": MAIN,
            "check_runs": [
                {"id": 11, "name": "validate", "app": "github-actions", "head_sha": HEAD,
                 "status": "completed", "conclusion": "success"},
                {"id": 12, "name": "lint", "app": "github-actions", "head_sha": HEAD,
                 "status": "completed", "conclusion": "success"},
            ],
            "reviews": [{"id": 21, "reviewer": BOT, "state": "APPROVED", "commit_id": HEAD,
                         "body": f"PASS\n\n{marker()}"}],
            "commits": [
                {"sha": PARENT, "author_login": "claude", "committer_login": "web-flow",
                 "message": "Change\n\nMaterial-Author: claude"},
                {"sha": HEAD, "author_login": "claude", "committer_login": "web-flow",
                 "message": "Change\n\nMaterial-Author: claude"},
            ],
            "review_threads": [
                {"id": "PRRT_1", "is_resolved": True, "is_outdated": False},
                {"id": "PRRT_2", "is_resolved": True, "is_outdated": True},
            ],
            "review_threads_complete": True,
        }, record)
        self.assertEqual(record, pr_observation(pull(), **inputs()))

    def test_end_to_end_report_is_consistent(self):
        data = snapshot(pr_observation(pull(), **inputs()))
        load_snapshot(data)
        self.assertEqual("CONSISTENT", build_report(data, NOW)["status"])

    def test_findings_still_reach_the_report(self):
        cases = {
            "unresolved thread": (
                lambda a: a.update(thread_pages=[thread_page([node("PRRT_1", resolved=False)])]),
                "review_threads"),
            "threads not paged to the end": (
                lambda a: a.update(thread_pages=[thread_page([node("PRRT_1")], has_next=True)]),
                "review_threads"),
            "no thread page fetched": (lambda a: a.update(thread_pages=[]), "review_threads"),
            "check run for another sha": (
                lambda a: a.update(check_run_pages=[
                    {"total_count": 2, "check_runs": [gh_run(11, "validate", head=OTHER),
                                                      gh_run(12, "lint")]}]),
                "required_checks"),
            "approval on another head": (
                lambda a: a.update(review_pages=[[gh_review(commit=OTHER)]]), "reviews"),
            "commit without linked account": (
                lambda a: a.update(commit_pages=[[gh_commit(PARENT), gh_commit(HEAD, author=None)]]),
                "commits"),
        }
        for label, (mutate, check) in cases.items():
            with self.subTest(label):
                args = inputs()
                mutate(args)
                report = build_report(snapshot(pr_observation(pull(), **args)), NOW)
                self.assertEqual("INCONSISTENT", report["status"])
                self.assertNotEqual([], report["findings"][check])

    def test_refuses_malformed_or_incomplete_payloads(self):
        cases = {
            "missing head sha": lambda p, a: p["head"].pop("sha"),
            "null base": lambda p, a: p.update(base=None),
            "boolean pr number": lambda p, a: p.update(number=True),
            "reviews incomplete": lambda p, a: a.update(reviews_complete=False),
            "commits incomplete": lambda p, a: a.update(commits_complete=False),
            "check runs incomplete": lambda p, a: a.update(check_runs_complete=False),
            "non-boolean completeness": lambda p, a: a.update(reviews_complete=1),
            "check runs short of total": lambda p, a: a["check_run_pages"].pop(),
            "check run totals disagree": lambda p, a: a["check_run_pages"][0].update(total_count=3),
            "no check run page": lambda p, a: a.update(check_run_pages=[]),
            "null check run app": lambda p, a: a["check_run_pages"][0]["check_runs"][0].update(app=None),
            "review without user": lambda p, a: a["review_pages"][0][0].update(user=None),
            "review body missing": lambda p, a: a["review_pages"][0][0].pop("body"),
            "review page not a list": lambda p, a: a.update(review_pages=[{"id": 1}]),
            "duplicate review": lambda p, a: a.update(review_pages=[[gh_review()], [gh_review()]]),
            "duplicate check run": lambda p, a: a.update(check_run_pages=[
                {"total_count": 2, "check_runs": [gh_run(11, "validate"), gh_run(11, "validate")]}]),
            "duplicate commit": lambda p, a: a.update(commit_pages=[[gh_commit(HEAD)], [gh_commit(HEAD)]]),
            "commit message missing": lambda p, a: a["commit_pages"][0][0]["commit"].pop("message"),
            "author login blank": lambda p, a: a["commit_pages"][0][0].update(author={"login": ""}),
            "non-boolean thread flag": lambda p, a: a["thread_pages"][1]["nodes"][0].update(isResolved="true"),
            "thread without pageInfo": lambda p, a: a["thread_pages"][1].pop("pageInfo"),
            "page after last page": lambda p, a: a["thread_pages"].append(thread_page([node("PRRT_9")])),
            "duplicate thread": lambda p, a: a["thread_pages"][1]["nodes"].append(node("PRRT_2")),
            "blank thread id": lambda p, a: a["thread_pages"][1]["nodes"].append(node("")),
            "bad issue": lambda p, a: a.update(issue=0),
            "bad recorded head": lambda p, a: a.update(recorded_head_sha=""),
        }
        for label, mutate in cases.items():
            with self.subTest(label):
                payload, args = pull(), copy.deepcopy(inputs())
                mutate(payload, args)
                with self.assertRaises(InvalidPayload):
                    pr_observation(payload, **args)

    def test_error_names_path_not_value(self):
        args = inputs()
        args["review_pages"][0][0]["user"] = {"login": 7}
        with self.assertRaises(InvalidPayload) as raised:
            pr_observation(pull(), **args)
        self.assertEqual("invalid reviews[0].user.login", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
