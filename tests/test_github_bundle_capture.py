"""OC-P0-01 (#395): whole-bundle capture composes main and PR captures consistently."""
import copy
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from github_bundle_capture import MAX_PULLS, capture_bundle  # noqa: E402
from github_bundle_snapshot import snapshot_from_bundle  # noqa: E402
from github_page_capture import CaptureError, Response  # noqa: E402
from test_github_bundle_snapshot import bundle  # noqa: E402
from test_github_pr_observation import HEAD  # noqa: E402

REPO = "NTinkicht/OneCompany"
BASE = f"/repos/{REPO}"
SECRET = "SECRET-BODY"


class Server:
    def __init__(self, refs=None):
        b = bundle()
        pr = b["pull_requests"][0]
        self.refs = refs or [b["main_ref"]]
        self.ref_calls = 0
        self.routes = {
            f"{BASE}/issues": b["issue_pages"], f"{BASE}/branches": b["branch_pages"],
            f"{BASE}/rules/branches/main": b["rule_pages"],
            f"{BASE}/pulls/9/reviews": pr["review_pages"], f"{BASE}/pulls/9/commits": pr["commit_pages"],
            f"{BASE}/commits/{HEAD}/check-runs": pr["check_run_pages"],
        }
        self.pull = pr["pull"]

    def __call__(self, path):
        parts = urlsplit(path)
        if parts.path == f"{BASE}/git/ref/heads/main":
            body = self.refs[min(self.ref_calls, len(self.refs) - 1)]
            self.ref_calls += 1
            return Response(200, body, None)
        if parts.path == f"{BASE}/pulls/9":
            return Response(200, self.pull, None)
        pages = self.routes.get(parts.path)
        if pages is None:
            return Response(404, {"message": SECRET}, None)
        number = int(dict(parse_qsl(parts.query)).get("page", "1"))
        link = None
        if number < len(pages):
            link = f'<https://api.github.com{parts.path}?{parts.query.split("&page=")[0]}&page={number + 1}>; rel="next"'
        return Response(200, pages[number - 1], link)


def caller_fields():
    b = bundle()
    return dict(
        observed_at=b["observed_at"], main_sha=b["main_sha"],
        active_lease_issue_ids=b["active_lease_issue_ids"],
        retired_pilot_issue_ids=b["retired_pilot_issue_ids"], write_attempts=b["write_attempts"],
        trusted_reviewers=b["trusted_reviewers"], app_slugs=b["app_slugs"])


def pull_spec(**changes):
    b = bundle()["pull_requests"][0]
    spec = {"number": 9, "issue": b["issue"], "recorded_head_sha": b["recorded_head_sha"],
            "thread_pages": b["thread_pages"], "ci_base_sha": b["ci_base_sha"]}
    spec.update(changes)
    return spec


def run(server=None, pulls=None, **kw):
    fields = dict(caller_fields(), **kw)
    return capture_bundle(server or Server(), REPO, [pull_spec()] if pulls is None else pulls, **fields)


class BundleCaptureTests(unittest.TestCase):
    def test_result_equals_the_reference_bundle_and_round_trips(self):
        result = run()
        self.assertEqual(bundle(), result)
        snapshot_from_bundle(result)

    def test_main_is_read_before_and_after_the_whole_capture(self):
        server = Server()
        run(server)
        self.assertEqual(3, server.ref_calls)

    def test_main_moving_before_pull_capture_or_at_the_end_is_refused(self):
        moved = copy.deepcopy(bundle()["main_ref"])
        moved["object"]["sha"] = "e" * 40
        for refs in ([bundle()["main_ref"], bundle()["main_ref"], moved], [bundle()["main_ref"], moved]):
            with self.assertRaises(CaptureError):
                run(Server(refs))

    def test_no_pulls_is_a_valid_empty_list(self):
        self.assertEqual([], run(pulls=[])["pull_requests"])

    def test_optional_pull_fields_are_optional(self):
        spec = pull_spec()
        del spec["ci_base_sha"], spec["thread_pages"]
        record = run(pulls=[spec])["pull_requests"][0]
        self.assertNotIn("ci_base_sha", record)
        self.assertEqual([], record["thread_pages"])

    def test_invalid_pull_lists_and_specs_are_refused(self):
        too_many = [pull_spec(number=n) for n in range(1, MAX_PULLS + 2)]
        bad = [
            "x", (), (pull_spec(),), {"number": 9}, too_many, [pull_spec(), pull_spec()], [pull_spec(extra=1)],
            [{"issue": 1, "recorded_head_sha": HEAD}], [pull_spec(number=True)], [pull_spec(number=0)],
            [pull_spec(), [pull_spec(number=10)]], [object()],
        ]
        for pulls in bad:
            with self.assertRaises(CaptureError):
                run(pulls=pulls)

    def test_none_pulls_are_refused(self):
        with self.assertRaises(CaptureError):
            capture_bundle(Server(), REPO, None, **caller_fields())

    def test_invalid_repo_is_refused_and_refusals_never_echo_bodies(self):
        with self.assertRaises(CaptureError):
            capture_bundle(Server(), "bad repo", [], **caller_fields())
        server = Server()
        server.routes.pop(f"{BASE}/pulls/9/reviews")
        with self.assertRaises(CaptureError) as ctx:
            run(server)
        self.assertNotIn(SECRET, str(ctx.exception))

    def test_caller_fields_are_copied_not_aliased(self):
        fields = caller_fields()
        fields["active_lease_issue_ids"] = [1]
        result = capture_bundle(Server(), REPO, [], **fields)
        fields["active_lease_issue_ids"].append(2)
        self.assertEqual([1], result["active_lease_issue_ids"])


if __name__ == "__main__":
    unittest.main()
