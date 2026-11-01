"""OC-P0-01 (#402): the gh-api Fetch adapter is GET-only and fails closed."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from github_gh_fetch import make_gh_fetch  # noqa: E402
from github_page_capture import CaptureError, Response, collect_pages  # noqa: E402

BASE = "/repos/NTinkicht/OneCompany"
SECRET = "ghp_SECRETTOKENVALUE"


def reply(status=200, body=None, headers=(), eol="\n", text="OK"):
    head = eol.join([f"HTTP/2.0 {status} {text}", "Content-Type: application/json", *headers])
    return head + eol + eol + json.dumps([] if body is None else body)


class Runner:
    def __init__(self, outputs):
        self.outputs, self.calls = list(outputs), []

    def __call__(self, argv):
        self.calls.append(argv)
        out = self.outputs.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def fetch_with(*outputs, **kw):
    runner = Runner(outputs)
    return make_gh_fetch(runner, **kw), runner


class FetchTests(unittest.TestCase):
    def test_returns_status_body_and_link(self):
        link = f'<https://api.github.com{BASE}/issues?per_page=100&page=2>; rel="next"'
        fetch, _ = fetch_with((0, reply(body=[1], headers=[f"Link: {link}"])))
        self.assertEqual(Response(200, [1], link), fetch(f"{BASE}/issues?per_page=100"))

    def test_crlf_and_lowercase_link_header(self):
        fetch, _ = fetch_with((0, reply(body={"a": 1}, headers=["link: <x>; rel=\"prev\""], eol="\r\n")))
        self.assertEqual(Response(200, {"a": 1}, '<x>; rel="prev"'), fetch(f"{BASE}/branches"))

    def test_argv_is_fixed_get_only_and_deterministic(self):
        fetch, runner = fetch_with((0, reply()), (0, reply()))
        fetch(f"{BASE}/issues?state=open")
        fetch(f"{BASE}/issues?state=open")
        self.assertEqual(runner.calls[0], runner.calls[1])
        self.assertEqual(
            ["gh", "api", "-i", "-X", "GET", "-H", "Accept: application/vnd.github+json",
             f"{BASE}/issues?state=open"], runner.calls[0])

    def test_non_200_is_returned_without_body_even_when_gh_exits_nonzero(self):
        fetch, _ = fetch_with((1, reply(404, {"message": SECRET}, text="Not Found")))
        self.assertEqual(Response(404, None, None), fetch(f"{BASE}/issues"))

    def test_collect_pages_follows_links_through_the_adapter(self):
        nxt = f'<{BASE}/issues?per_page=100&page=2>; rel="next"'
        fetch, runner = fetch_with((0, reply(body=[1], headers=[f"Link: {nxt}"])), (0, reply(body=[2])))
        self.assertEqual(([[1], [2]], True), collect_pages(fetch, f"{BASE}/issues?per_page=100"))
        self.assertEqual(2, len(runner.calls))

    def test_collect_pages_refuses_non_200_naming_status_only(self):
        fetch, _ = fetch_with((1, reply(403, {"message": SECRET}, text="Forbidden")))
        with self.assertRaises(CaptureError) as ctx:
            collect_pages(fetch, f"{BASE}/issues?per_page=100")
        self.assertIn("403", str(ctx.exception))
        self.assertNotIn(SECRET, str(ctx.exception))


class RefusalTests(unittest.TestCase):
    def refused(self, *outputs, path=f"{BASE}/issues", **kw):
        fetch, _ = fetch_with(*outputs, **kw)
        with self.assertRaises(CaptureError) as ctx:
            fetch(path)
        self.assertNotIn(SECRET, str(ctx.exception))
        return str(ctx.exception)

    def test_bad_paths_never_reach_the_runner(self):
        for path in ("https://api.github.com" + BASE + "/issues", "/user", "repos/a/b/issues",
                     f"{BASE}/../x", f"{BASE}//issues", f"{BASE}/issues#frag", f"{BASE}/issues\n",
                     f"{BASE}/is sues", "/repos/a/b/../../user", f"{BASE}/issues?x=$(id)", "", None):
            fetch, runner = fetch_with()
            with self.assertRaises(CaptureError):
                fetch(path)
            self.assertEqual([], runner.calls)

    def test_runner_exceptions_become_a_fixed_refusal(self):
        for exc in (OSError(SECRET), TimeoutError(SECRET), ValueError(SECRET)):
            self.assertEqual("transport failed", self.refused(exc))

    def test_bad_runner_result_shapes_are_refused(self):
        for result in ("x", (0,), (0, b"bytes"), ("0", "x"), None):
            self.assertEqual("transport failed", self.refused(result))

    def test_oversize_output_is_refused(self):
        self.assertEqual("response too large", self.refused((0, reply(body=[SECRET] * 50)), max_bytes=100))

    def test_malformed_header_blocks_are_refused(self):
        for out in ("", "no status line\n\n[]", "HTTP/2.0 200 OK\nbad header line\n\n[]",
                    "HTTP/2.0 abc OK\n\n[]"):
            self.assertEqual("malformed response", self.refused((0, out)))

    def test_ok_without_blank_line_or_with_duplicate_link_or_nonzero_exit_is_refused(self):
        self.assertEqual("malformed response", self.refused((0, "HTTP/2.0 200 OK\nX: y")))
        two = reply(headers=['Link: <a>; rel="next"', 'Link: <b>; rel="next"'])
        self.assertEqual("malformed response", self.refused((0, two)))
        self.assertEqual("malformed response", self.refused((1, reply())))

    def test_non_json_body_on_200_is_refused_without_the_body(self):
        out = f"HTTP/2.0 200 OK\n\n<html>{SECRET}</html>"
        self.assertEqual("malformed body", self.refused((0, out)))

    def test_invalid_max_bytes_is_refused(self):
        for bad in (0, -1, True, "5", None):
            with self.assertRaises(CaptureError):
                make_gh_fetch(Runner([]), max_bytes=bad)


if __name__ == "__main__":
    unittest.main()
