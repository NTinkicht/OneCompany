"""OC-P0-01 (#389): paginated page capture with honest completeness flags."""
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from github_bundle_snapshot import snapshot_from_bundle  # noqa: E402
from github_page_capture import (  # noqa: E402
    CaptureError, Response, capture_pull_pages, capture_repo_pages, collect_pages, next_path)
from live_reconciliation_report import build_report  # noqa: E402
from test_github_bundle_snapshot import bundle  # noqa: E402
from test_github_pr_observation import HEAD, NOW  # noqa: E402

REPO = "NTinkicht/OneCompany"
BASE = f"/repos/{REPO}"


class Server:
    """Serves each route's pages; page N is the Nth body, with a Link to N+1."""

    def __init__(self, routes, host="https://api.github.com", link_for=None):
        self.routes, self.host, self.link_for, self.calls = routes, host, link_for, []

    def __call__(self, path):
        self.calls.append(path)
        parts = urlsplit(path)
        pages = self.routes.get(parts.path)
        if pages is None:
            return Response(404, {"message": "secret body"}, None)
        query = dict(parse_qsl(parts.query))
        number = int(query.get("page", "1"))
        link = None
        if number < len(pages):
            link = self.link_for(parts, number + 1) if self.link_for else (
                f'<{self.host}{parts.path}?{parts.query.split("&page=")[0]}&page={number + 1}>; rel="next"')
        return Response(200, pages[number - 1], link)


def routes_from_bundle():
    b = bundle()
    pr = b["pull_requests"][0]
    return {
        f"{BASE}/issues": b["issue_pages"], f"{BASE}/branches": b["branch_pages"],
        f"{BASE}/rules/branches/main": b["rule_pages"],
        f"{BASE}/pulls/7/reviews": pr["review_pages"], f"{BASE}/pulls/7/commits": pr["commit_pages"],
        f"{BASE}/commits/{HEAD}/check-runs": pr["check_run_pages"],
    }


class CollectTests(unittest.TestCase):
    def test_follows_every_page_and_reports_complete(self):
        server = Server({f"{BASE}/issues": [[1], [2], [3]]})
        pages, complete = collect_pages(server, f"{BASE}/issues?state=open&per_page=100")
        self.assertEqual(([[1], [2], [3]], True), (pages, complete))
        self.assertEqual(3, len(server.calls))

    def test_max_pages_with_next_pending_is_incomplete(self):
        pages, complete = collect_pages(Server({f"{BASE}/issues": [[1], [2], [3]]}), f"{BASE}/issues?per_page=100", max_pages=2)
        self.assertEqual(([[1], [2]], False), (pages, complete))

    def test_max_pages_on_the_last_page_is_complete(self):
        pages, complete = collect_pages(Server({f"{BASE}/issues": [[1], [2]]}), f"{BASE}/issues?per_page=100", max_pages=2)
        self.assertEqual(([[1], [2]], True), (pages, complete))

    def test_single_page_without_link_is_complete(self):
        self.assertEqual(([[]], True), collect_pages(lambda p: Response(200, [], None), f"{BASE}/issues"))

    def test_invalid_arguments(self):
        for kwargs in ({"max_pages": 0}, {"max_pages": True}, {"expect": tuple}):
            with self.assertRaises(CaptureError):
                collect_pages(lambda p: Response(200, [], None), f"{BASE}/issues", **kwargs)
        for path in ("https://evil.example/repos/x", "repos/x", "//evil.example/x"):
            with self.assertRaises(CaptureError):
                collect_pages(lambda p: Response(200, [], None), path)

    def test_non_200_names_status_only(self):
        with self.assertRaises(CaptureError) as ctx:
            collect_pages(Server({}), f"{BASE}/issues")
        self.assertEqual("status 404 on page 0", str(ctx.exception))
        self.assertNotIn("secret", str(ctx.exception))

    def test_wrong_body_type_and_bad_response_refused(self):
        for response in (Response(200, {"a": 1}, None), Response(200, None, None), (200, [], None), Response("200", [], None)):
            with self.assertRaises(CaptureError):
                collect_pages(lambda p, r=response: r, f"{BASE}/issues")
        with self.assertRaises(CaptureError):
            collect_pages(lambda p: Response(200, [], None), f"{BASE}/issues", expect=dict)

    def test_second_page_failure_is_not_partial(self):
        calls = []

        def fetch(path):
            calls.append(path)
            if len(calls) == 1:
                return Response(200, [1], f'<{BASE}/issues?per_page=100&page=2>; rel="next"')
            return Response(500, "boom", None)

        with self.assertRaises(CaptureError):
            collect_pages(fetch, f"{BASE}/issues?per_page=100")

    def test_loop_is_refused(self):
        loop = Response(200, [1], f'<{BASE}/issues?per_page=100>; rel="next"')
        with self.assertRaises(CaptureError):
            collect_pages(lambda p: loop, f"{BASE}/issues?per_page=100")


class NextLinkTests(unittest.TestCase):
    ENDPOINT, KEYS = f"{BASE}/issues", frozenset({"per_page", "state", "page"})

    def next(self, link):
        return next_path(link, self.ENDPOINT, self.KEYS)

    def test_absent_or_other_rel_is_none(self):
        for link in (None, "", f'<https://api.github.com{BASE}/issues?page=9>; rel="last"'):
            self.assertIsNone(self.next(link))

    def test_picks_next_among_several_rels(self):
        link = (f'<https://api.github.com{BASE}/issues?page=1>; rel="prev", '
                f'<https://api.github.com{BASE}/issues?per_page=100&page=3>; rel="next", '
                f'<https://api.github.com{BASE}/issues?page=9>; rel="last"')
        self.assertEqual(f"{BASE}/issues?per_page=100&page=3", self.next(link))

    def test_bare_path_is_accepted(self):
        self.assertEqual(f"{BASE}/issues?page=2", self.next(f'<{BASE}/issues?page=2>; rel="next"'))

    def test_refusals(self):
        bad = [
            f'<https://evil.example{BASE}/issues?page=2>; rel="next"',
            f'<http://api.github.com{BASE}/issues?page=2>; rel="next"',
            f'<https://api.github.com.evil.example{BASE}/issues?page=2>; rel="next"',
            f'<https://user:pw@api.github.com{BASE}/issues?page=2>; rel="next"',
            f'<{BASE}/pulls?page=2>; rel="next"',
            f'<{BASE}/issues/../pulls?page=2>; rel="next"',
            f'<{BASE}/issues?page=2#frag>; rel="next"',
            f'<{BASE}/issues?page=2&access_token=x>; rel="next"',
            f'<{BASE}/issues?page=2&page=3>; rel="next"',
            f'<{BASE}/issues?page=2>; rel="next", <{BASE}/issues?page=3>; rel="next"',
            5,
        ]
        for link in bad:
            with self.subTest(link=link), self.assertRaises(CaptureError):
                self.next(link)

    def test_foreign_next_stops_collection_without_requesting_it(self):
        server = Server({f"{BASE}/issues": [[1], [2]]}, host="https://evil.example")
        with self.assertRaises(CaptureError):
            collect_pages(server, f"{BASE}/issues?per_page=100")
        self.assertEqual(1, len(server.calls))


class CaptureTests(unittest.TestCase):
    def test_repo_keys_and_paths(self):
        server = Server(routes_from_bundle())
        out = capture_repo_pages(server, REPO)
        self.assertEqual(
            {"issue_pages", "issues_complete", "branch_pages", "branches_complete", "rule_pages", "rules_complete"}, set(out))
        self.assertTrue(out["issues_complete"] and out["branches_complete"] and out["rules_complete"])
        self.assertIn(f"{BASE}/issues?state=open&per_page=100", server.calls)

    def test_end_to_end_into_the_bundle(self):
        b = bundle()
        server = Server(routes_from_bundle())
        b.update(capture_repo_pages(server, REPO))
        b["pull_requests"][0].update(capture_pull_pages(server, REPO, 7, HEAD))
        self.assertEqual("CONSISTENT", build_report(snapshot_from_bundle(b), NOW)["status"])

    def test_truncated_capture_is_refused_by_the_bundle(self):
        b = bundle()
        routes = routes_from_bundle()
        routes[f"{BASE}/issues"] = routes[f"{BASE}/issues"] * 3
        out = capture_repo_pages(Server(routes), REPO, max_pages=1)
        self.assertFalse(out["issues_complete"])
        b.update(out)
        with self.assertRaises(Exception):
            snapshot_from_bundle(b)

    def test_check_runs_expect_objects(self):
        server = Server(routes_from_bundle())
        out = capture_pull_pages(server, REPO, 7, HEAD)
        self.assertTrue(all(type(p) is dict for p in out["check_run_pages"]))

    def test_inputs_cannot_reach_other_paths(self):
        fetch = Server(routes_from_bundle())
        for repo in ("a", "a/b/c", "../x", "a/..", "./x", "a b/c", "o/r?x=1", "o/r#f", 5, None):
            with self.subTest(repo=repo), self.assertRaises(CaptureError):
                capture_repo_pages(fetch, repo)
        for number in (0, -1, True, "7", 7.0):
            with self.subTest(number=number), self.assertRaises(CaptureError):
                capture_pull_pages(fetch, REPO, number, HEAD)
        for sha in ("", "c" * 39, "C" * 40, HEAD + "/x", f"{HEAD[:-3]}../", None):
            with self.subTest(sha=sha), self.assertRaises(CaptureError):
                capture_pull_pages(fetch, REPO, 7, sha)
        self.assertEqual([], fetch.calls)


if __name__ == "__main__":
    unittest.main()
