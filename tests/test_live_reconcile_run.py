"""OC-P0-01 (#521): the live-reconcile command wires gh-api fetch into reconcile_live fail-closed."""
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import live_reconcile_run as cli  # noqa: E402
from github_live_reconcile import reconcile_live  # noqa: E402
from github_gh_fetch import make_gh_fetch  # noqa: E402
from live_reconciliation_report import render  # noqa: E402
from test_github_bundle_capture import REPO, SECRET, Server, caller_fields, pull_spec  # noqa: E402
from test_github_pr_observation import NOW  # noqa: E402


def gh_runner(server, calls=None):
    """Serve the existing fixture Server as ``gh api -i`` output."""
    def runner(argv):
        if calls is not None:
            calls.append(list(argv))
        resp = server(argv[-1])
        head = [f"HTTP/2.0 {resp.status} X", "Content-Type: application/json"]
        if resp.link:
            head.append(f"Link: {resp.link}")
        return (0, "\n".join(head) + "\n\n" + json.dumps(resp.body))
    return runner


def inputs(**changes):
    data = {k: v for k, v in caller_fields().items() if k != "observed_at"}
    data["pulls"] = [pull_spec()]
    data.update(changes)
    return data


class Cli(unittest.TestCase):
    def run_cli(self, data=None, raw=None, runner=None, repo=REPO, clock=None, extra=()):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "in.json"
            path.write_text(raw if raw is not None else json.dumps(data), encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = cli.main(["--repo", repo, "--inputs", str(path), *extra], runner=runner,
                                clock=clock or (lambda: NOW))
        return code, out.getvalue(), err.getvalue()

    def test_verdict_and_exit_match_reconcile_live(self):
        calls = []
        code, out, err = self.run_cli(inputs(), runner=gh_runner(Server(), calls))
        fields = caller_fields()
        fields["observed_at"] = NOW.isoformat()
        expected = reconcile_live(make_gh_fetch(gh_runner(Server())), REPO, [pull_spec()], now=NOW, **fields)
        self.assertEqual(render(expected), out)
        self.assertEqual(0 if expected["status"] == "CONSISTENT" else 1, code)
        self.assertEqual("", err)
        self.assertTrue(calls)

    def test_every_runner_argv_is_a_get_gh_api_repo_path(self):
        calls = []
        self.run_cli(inputs(), runner=gh_runner(Server(), calls))
        for argv in calls:
            self.assertEqual(["gh", "api", "-i", "-X", "GET"], argv[:5])
            self.assertTrue(argv[-1].startswith(f"/repos/{REPO}/"), argv)

    def refused(self, *a, **kw):
        calls = kw.pop("calls", [])
        code, out, err = self.run_cli(*a, **kw)
        self.assertEqual(2, code, err)
        self.assertEqual("", out)
        self.assertIn("UNABLE TO VERIFY", err)
        self.assertNotIn(SECRET, err)
        return calls

    def test_bad_inputs_are_refused_before_any_network_call(self):
        calls = []
        runner = gh_runner(Server(), calls)
        good = inputs()
        missing = {k: v for k, v in good.items() if k != "app_slugs"}
        for kw in ({"data": missing}, {"data": {**good, "extra": 1}}, {"data": []},
                   {"raw": "not json"}, {"data": good, "repo": "bad repo"}):
            with self.subTest(kw=list(kw)):
                self.refused(runner=runner, **kw)
        self.assertEqual([], calls)

    def test_runner_failures_and_non_200_are_refused_without_leaking_text(self):
        def raising(argv):
            raise OSError(SECRET)
        self.refused(inputs(), runner=raising)
        self.refused(inputs(), runner=lambda argv: (0, f"HTTP/2.0 500 {SECRET}\n\n{{}}"))

    def test_main_moving_during_capture_is_refused(self):
        import copy
        from test_github_bundle_snapshot import bundle
        moved = copy.deepcopy(bundle()["main_ref"])
        moved["object"]["sha"] = "f" * 40
        self.refused(inputs(), runner=gh_runner(Server(refs=[bundle()["main_ref"], moved])))

    def test_stale_baseline_main_sha_is_reported_not_refused(self):
        code, out, _ = self.run_cli(inputs(main_sha="e" * 40), runner=gh_runner(Server()))
        self.assertEqual(1, code)
        self.assertIn("INCONSISTENT", out)

    def test_freshness_uses_a_clock_sampled_after_capture(self):
        import datetime as dt
        ticks = iter([NOW, NOW + dt.timedelta(seconds=120)])  # start, then after slow capture
        code, out, _ = self.run_cli(inputs(), runner=gh_runner(Server()),
                                    clock=lambda: next(ticks), extra=("--max-age-seconds", "30"))
        self.assertEqual(1, code)
        self.assertIn("INCONSISTENT", out)
        self.assertIn("freshness", out)

    def findings(self, **changes):
        """Run the CLI on the baseline ``inputs()`` overridden by ``changes``, served by the
        fixture ``Server()`` through ``gh_runner`` (no network); return (exit code, findings dict)."""
        code, out, err = self.run_cli(inputs(**changes), runner=gh_runner(Server()))
        self.assertEqual("", err)
        return code, json.loads(out)["findings"]

    def test_clean_baseline_has_no_findings_in_any_section(self):
        code, found = self.findings()
        self.assertEqual(0, code)
        self.assertTrue(all(v == [] for v in found.values()), found)

    def test_active_lease_with_no_matching_work_is_an_orphan_lease(self):
        code, found = self.findings(active_lease_issue_ids=[1, 999])
        self.assertEqual(1, code)
        self.assertIn("ORPHAN_LEASE", found["snapshot"])

    def test_retired_pilot_branch_is_reported_as_reactivated(self):
        code, found = self.findings(retired_pilot_issue_ids=[1])
        self.assertEqual(1, code)
        self.assertIn(["ai/1-feature", "RETIRED_PILOT_REACTIVATED"], found["branches"])

    def test_untrusted_reviewer_approval_is_not_accepted(self):
        # The fixture approval is by ntk-reviewer[bot]; trusting only another login must
        # surface UNTRUSTED_REVIEWER_APPROVAL (review 21 on PR 9). The clean control must not.
        _, clean = self.findings()
        self.assertNotIn("UNTRUSTED_REVIEWER_APPROVAL", [f[2] for f in clean["reviews"]])
        code, found = self.findings(trusted_reviewers=["other[bot]"])
        self.assertEqual(1, code)
        self.assertIn([9, "21", "UNTRUSTED_REVIEWER_APPROVAL"], found["reviews"])

    def test_recorded_head_that_differs_from_live_head_is_stale(self):
        spec = pull_spec(recorded_head_sha="d" * 40)
        code, out, _ = self.run_cli(inputs(pulls=[spec]), runner=gh_runner(Server()))
        self.assertEqual(1, code)
        self.assertIn([9, "STALE_PR_HEAD"], json.loads(out)["findings"]["pull_requests"])

    def test_replay_of_unknown_work_is_flagged(self):
        attempt = {"operation_id": "op-1", "issue": 777, "outcome": "unknown"}
        code, found = self.findings(write_attempts=[attempt])
        self.assertEqual(1, code)
        self.assertIn(["op-1", "ORPHAN_REPLAY"], found["write_attempts"])

    def test_duplicate_operation_id_is_flagged(self):
        attempt = {"operation_id": "op-1", "issue": 1, "outcome": "success", "readback": "present"}
        code, found = self.findings(write_attempts=[attempt, dict(attempt)])
        self.assertEqual(1, code)
        self.assertIn(["op-1", "DUPLICATE_OPERATION"], found["write_attempts"])

    def test_registry_routes_to_script(self):
        r = subprocess.run([sys.executable, str(ROOT / "onecompany.py"), "live-reconcile", "--help"],
                           capture_output=True, text=True)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("--inputs", r.stdout)


if __name__ == "__main__":
    unittest.main()
