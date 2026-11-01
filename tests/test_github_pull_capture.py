"""OC-P0-01 (#391): single-PR capture refuses head/base movement mid-capture."""
import copy
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from github_bundle_snapshot import snapshot_from_bundle  # noqa: E402
from github_page_capture import CaptureError, Response  # noqa: E402
from github_pull_capture import capture_pull_request  # noqa: E402
from test_github_bundle_snapshot import bundle  # noqa: E402
from test_github_pr_observation import HEAD  # noqa: E402

REPO = "NTinkicht/OneCompany"
BASE = f"/repos/{REPO}"


class Server:
    def __init__(self, pulls=None, status=200, secret="SECRET-BODY"):
        b = bundle()["pull_requests"][0]
        self.pr = b
        self.pulls = pulls or [b["pull"], b["pull"]]
        self.status, self.secret, self.pull_calls = status, secret, 0
        self.routes = {
            f"{BASE}/pulls/9/reviews": b["review_pages"], f"{BASE}/pulls/9/commits": b["commit_pages"],
            f"{BASE}/commits/{HEAD}/check-runs": b["check_run_pages"],
        }

    def __call__(self, path):
        parts = urlsplit(path)
        if parts.path == f"{BASE}/pulls/9":
            body = self.pulls[min(self.pull_calls, len(self.pulls) - 1)]
            self.pull_calls += 1
            return Response(self.status, body if self.status == 200 else {"message": self.secret}, None)
        pages = self.routes.get(parts.path)
        if pages is None:
            return Response(404, {"message": self.secret}, None)
        number = int(dict(parse_qsl(parts.query)).get("page", "1"))
        link = None
        if number < len(pages):
            link = f'<https://api.github.com{parts.path}?per_page=100&page={number + 1}>; rel="next"'
        return Response(200, pages[number - 1], link)


def call(server, **kw):
    args = dict(issue=5, recorded_head_sha=HEAD)
    args.update(kw)
    return capture_pull_request(server, REPO, 9, **args)


def moved(field, sha):
    pull = copy.deepcopy(bundle()["pull_requests"][0]["pull"])
    pull[field]["sha"] = sha
    return pull


class PullCaptureTests(unittest.TestCase):
    def test_record_round_trips_through_snapshot(self):
        server = Server()
        record = call(server)
        self.assertEqual(server.pull_calls, 2)
        full = bundle()
        full["pull_requests"] = [dict(record, thread_pages=full["pull_requests"][0]["thread_pages"])]
        snapshot_from_bundle(full)
        for flag in ("reviews_complete", "check_runs_complete", "commits_complete"):
            self.assertIs(record[flag], True)

    def test_default_threads_are_empty_so_report_fails_closed(self):
        self.assertEqual(call(Server())["thread_pages"], [])

    def test_head_movement_is_refused(self):
        original = bundle()["pull_requests"][0]["pull"]
        with self.assertRaisesRegex(CaptureError, "moved"):
            call(Server(pulls=[original, moved("head", "d" * 40)]))

    def test_base_movement_is_refused(self):
        original = bundle()["pull_requests"][0]["pull"]
        with self.assertRaisesRegex(CaptureError, "moved"):
            call(Server(pulls=[original, moved("base", "e" * 40)]))

    def test_non_200_is_refused_without_body(self):
        with self.assertRaises(CaptureError) as ctx:
            call(Server(status=500))
        self.assertIn("500", str(ctx.exception))
        self.assertNotIn("SECRET", str(ctx.exception))

    def test_bad_pull_bodies_are_refused(self):
        good = bundle()["pull_requests"][0]["pull"]
        for bad in (
            [], dict(good, number=8), dict(good, number=True), dict(good, number="9"), dict(good, number=None),
            moved("head", "ABC"), moved("head", "a" * 39), moved("base", ""),
            {k: v for k, v in good.items() if k != "head"},
        ):
            with self.subTest(bad=str(bad)[:40]), self.assertRaises(CaptureError):
                call(Server(pulls=[bad, bad]))

    def test_second_fetch_bad_body_is_refused(self):
        good = bundle()["pull_requests"][0]["pull"]
        with self.assertRaises(CaptureError):
            call(Server(pulls=[good, []]))

    def test_invalid_arguments_are_refused(self):
        for kw in ({"issue": 0}, {"issue": True}, {"recorded_head_sha": ""}, {"thread_pages": "x"}):
            with self.subTest(kw=kw), self.assertRaises(CaptureError):
                call(Server(), **kw)
        with self.assertRaises(CaptureError):
            capture_pull_request(Server(), "bad repo", 7, issue=5, recorded_head_sha=HEAD)
        with self.assertRaises(CaptureError):
            capture_pull_request(Server(), REPO, 0, issue=5, recorded_head_sha=HEAD)

    def test_incomplete_listing_stays_incomplete(self):
        server = Server()
        server.routes[f"{BASE}/pulls/9/reviews"] = server.routes[f"{BASE}/pulls/9/reviews"] * 3
        record = call(server, max_pages=1)
        self.assertEqual(len(record["review_pages"]), 1)
        self.assertIs(record["reviews_complete"], False)


if __name__ == "__main__":
    unittest.main()
