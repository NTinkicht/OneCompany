"""OC-P0-01 (#363): one fail-closed reconciliation report over a live snapshot."""
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
NOW = dt.datetime(2026, 10, 25, 14, 0, tzinfo=dt.timezone.utc)


def doc():
    """A fully consistent, fresh snapshot."""
    return {
        "schema_version": 1,
        "observed_at": "2026-10-25T13:55:00+00:00",
        "snapshot": {
            "main_sha": MAIN, "observed_main_sha": MAIN,
            "issue_ids": [1, 2, 3], "next_ids": [2],
            "pr_issue_bindings": [[9, 1]], "active_lease_issue_ids": [1],
            "retired_pilot_issue_ids": [], "ineligible_issue_ids": [],
        },
        "pull_requests": [{
            "pr": 9, "issue": 1, "recorded_head_sha": HEAD, "observed_head_sha": HEAD,
            "base_sha": MAIN, "approved_head_sha": HEAD, "approved_base_sha": MAIN,
            "ci_head_sha": HEAD, "ci_base_sha": MAIN, "ci_conclusion": "success",
            "merge_ready_claimed": True, "approved_by": "ntk-reviewer[bot]",
            "material_authors": ["claude"],
        }],
        "branches": ["main", "ai/1-feature"],
        "write_attempts": [{"operation_id": "op-1", "issue": 1, "outcome": "success",
                            "readback": "present"}],
        "trusted_reviewers": ["ntk-reviewer[bot]"],
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
            "pull_requests": (lambda d: d["pull_requests"][0].update(approved_by="claude"), [9, "UNTRUSTED_APPROVAL"]),
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


class LoaderTests(unittest.TestCase):
    def test_strict_loader_refuses_malformed_input(self):
        mutations = [
            lambda d: d.pop("branches"),
            lambda d: d.update(extra=1),
            lambda d: d.update(schema_version=2),
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
            lambda d: d["pull_requests"][0].update(material_authors="claude"),
            lambda d: d["pull_requests"][0].pop("base_sha"),
            lambda d: d.update(pull_requests={}),
            lambda d: d["write_attempts"][0].update(retries=False),
            lambda d: d["write_attempts"][0].update(safety_rejected=1),
            lambda d: d.update(branches="ai/1-feature"),
            lambda d: d.update(trusted_reviewers=[None]),
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

        for text in ["{not json", "[]", json.dumps({**doc(), "schema_version": 2})]:
            code, out, err = self.run_cli(text)
            self.assertEqual((EXIT_INVALID, ""), (code, out))
            self.assertTrue(err.startswith("invalid snapshot:"))

    def test_missing_file_is_invalid(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(EXIT_INVALID, main(["/nonexistent/snapshot.json"], now=NOW))


if __name__ == "__main__":
    unittest.main()
