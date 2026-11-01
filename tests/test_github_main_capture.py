"""OC-P0-01 (#393): main-ref capture refuses main movement mid-capture."""
import copy
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from github_bundle_snapshot import snapshot_from_bundle  # noqa: E402
from github_main_capture import capture_main  # noqa: E402
from github_page_capture import CaptureError, Response  # noqa: E402
from test_github_bundle_snapshot import bundle  # noqa: E402

REPO = "NTinkicht/OneCompany"
BASE = f"/repos/{REPO}"
SECRET = "SECRET-BODY"


def ref_with(**changes):
    ref = copy.deepcopy(bundle()["main_ref"])
    for key, value in changes.items():
        if key in ("type", "sha"):
            ref["object"][key] = value
        else:
            ref[key] = value
    return ref


class Server:
    def __init__(self, refs=None, status=200):
        b = bundle()
        self.refs = refs or [b["main_ref"], b["main_ref"]]
        self.status, self.ref_calls = status, 0
        self.routes = {
            f"{BASE}/issues": b["issue_pages"], f"{BASE}/branches": b["branch_pages"],
            f"{BASE}/rules/branches/main": b["rule_pages"],
        }

    def __call__(self, path):
        parts = urlsplit(path)
        if parts.path == f"{BASE}/git/ref/heads/main":
            body = self.refs[min(self.ref_calls, len(self.refs) - 1)]
            self.ref_calls += 1
            return Response(self.status, body if self.status == 200 else {"message": SECRET}, None)
        pages = self.routes.get(parts.path)
        if pages is None:
            return Response(404, {"message": SECRET}, None)
        number = int(dict(parse_qsl(parts.query)).get("page", "1"))
        link = None
        if number < len(pages):
            link = f'<https://api.github.com{parts.path}?{parts.query.split("&page=")[0]}&page={number + 1}>; rel="next"'
        return Response(200, pages[number - 1], link)


class MainCaptureTests(unittest.TestCase):
    def test_result_merges_into_bundle_that_round_trips(self):
        server = Server()
        result = capture_main(server, REPO)
        self.assertEqual(server.ref_calls, 2)
        self.assertEqual(result["main_sha"], bundle()["main_ref"]["object"]["sha"])
        full = bundle()
        full.update(result)
        snapshot_from_bundle(full)
        for flag in ("issues_complete", "branches_complete", "rules_complete"):
            self.assertIs(result[flag], True)

    def test_main_movement_is_refused(self):
        original = bundle()["main_ref"]
        with self.assertRaisesRegex(CaptureError, "moved"):
            capture_main(Server(refs=[original, ref_with(sha="d" * 40)]), REPO)

    def test_invalid_ref_payloads_are_refused(self):
        for changes in ({"ref": "refs/heads/dev"}, {"type": "tag"}, {"sha": "xyz"}, {"sha": "A" * 40}):
            with self.assertRaises(CaptureError, msg=str(changes)):
                capture_main(Server(refs=[ref_with(**changes)]), REPO)
        for body in ([], "x", None, {"ref": "refs/heads/main"}, {"ref": "refs/heads/main", "object": []}):
            with self.assertRaises(CaptureError):
                capture_main(Server(refs=[body]), REPO)

    def test_second_ref_read_is_validated(self):
        with self.assertRaises(CaptureError):
            capture_main(Server(refs=[bundle()["main_ref"], ref_with(type="tag")]), REPO)

    def test_non_200_refused_without_body(self):
        with self.assertRaises(CaptureError) as ctx:
            capture_main(Server(status=403), REPO)
        self.assertNotIn(SECRET, str(ctx.exception))
        self.assertIn("403", str(ctx.exception))

    def test_invalid_response_object_refused(self):
        with self.assertRaises(CaptureError):
            capture_main(lambda path: (200, {}, None), REPO)

    def test_invalid_repo_refused(self):
        for repo in ("", "a", "a/b/c", "../x", None, "a/.."):
            with self.assertRaises(CaptureError):
                capture_main(Server(), repo)

    def test_truncated_listing_stays_incomplete(self):
        server = Server()
        server.routes[f"{BASE}/issues"] = copy.deepcopy(server.routes[f"{BASE}/issues"]) * 2
        result = capture_main(server, REPO, max_pages=1)
        self.assertIs(result["issues_complete"], False)
        self.assertEqual(len(result["issue_pages"]), 1)


if __name__ == "__main__":
    unittest.main()
