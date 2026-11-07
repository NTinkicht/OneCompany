import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import outcome_report as orp  # noqa: E402

ALLOWED, FORBIDDEN = orp.load_budget(ROOT)


def rec(wu, event, at, cost="LOCAL", **extra):
    return {"wu": wu, "event": event, "at": at, "cost_class": cost, **extra}


GOOD = [
    rec("WU-A", "started", "2026-11-03T10:00:00Z"),
    rec("WU-A", "gate_pending", "2026-11-03T10:10:00Z", "HUMAN"),
    rec("WU-A", "incident", "2026-11-03T10:20:00Z", "LOCAL"),
    rec("WU-A", "merged", "2026-11-03T11:00:30Z", "INCLUDED_SUBSCRIPTION", outcome="merged", tokens=120),
    rec("WU-B", "started", "2026-11-03T09:00:00+00:00", "FREE_ALLOWANCE"),
]


class OutcomeReportTests(unittest.TestCase):
    def report(self, receipts):
        return orp.build_report(receipts, ALLOWED, FORBIDDEN)

    def row(self, report, wu):
        return next(r for r in report["work_units"] if r["wu"] == wu)

    def test_metrics_match_receipts_exactly_and_are_deterministic(self):
        first = self.report(GOOD)
        self.assertEqual(first, self.report(list(GOOD)))
        a = self.row(first, "WU-A")
        self.assertEqual((a["outcome"], a["latency_seconds"], a["incidents"], a["pending_gates"], a["tokens"], a["confidence"]),
                         ("merged", 3630, 1, 1, 120, "high"))
        self.assertEqual(a["cost_classes"], {"HUMAN": 1, "INCLUDED_SUBSCRIPTION": 1, "LOCAL": 2})
        self.assertTrue(first["zero_spend_ok"])
        self.assertEqual([r["wu"] for r in first["work_units"]], ["WU-A", "WU-B"])

    def test_missing_end_event_is_low_confidence_without_invented_latency(self):
        b = self.row(self.report(GOOD), "WU-B")
        self.assertIsNone(b["latency_seconds"])
        self.assertIsNone(b["outcome"])
        self.assertIsNone(b["tokens"])
        self.assertEqual(b["confidence"], "low")

    def test_bad_or_naive_timestamps_are_low_confidence(self):
        rows = [rec("WU-C", "started", "not-a-time"), rec("WU-C", "merged", "2026-11-03T10:00:00", outcome="merged")]
        c = self.row(self.report(rows), "WU-C")
        self.assertIsNone(c["latency_seconds"])
        self.assertEqual(c["confidence"], "low")

    def test_zero_spend_flags_forbidden_unknown_and_missing_cost_classes(self):
        for bad in ("METERED_ALLOWED", "METERED_FORBIDDEN", "UNKNOWN_COST", "SOMETHING_NEW"):
            report = self.report([rec("WU-D", "started", "2026-11-03T10:00:00Z", bad)])
            self.assertFalse(report["zero_spend_ok"], bad)
            self.assertEqual(len(report["violations"]), 1)
        missing = self.report([{"wu": "WU-D", "event": "started", "at": "2026-11-03T10:00:00Z"}])
        self.assertFalse(missing["zero_spend_ok"])
        self.assertEqual(missing["violations"][0]["cost_class"], "MISSING")

    def test_tokens_are_never_estimated_or_taken_from_invalid_values(self):
        rows = [rec("WU-E", "started", "2026-11-03T10:00:00Z", tokens=-5), rec("WU-E", "merged", "2026-11-03T10:01:00Z", tokens=True, outcome="merged")]
        self.assertIsNone(self.row(self.report(rows), "WU-E")["tokens"])

    def test_secret_like_and_unexpected_values_are_redacted_from_output(self):
        secret = "ghp_" + "A" * 30
        rows = [rec(secret, "started", "2026-11-03T10:00:00Z", note="Bearer abc.def", prompt="do the thing"),
                rec("WU-F", "merged", "2026-11-03T10:05:00Z", outcome="sk-" + "b" * 24)]
        dumped = json.dumps(self.report(rows))
        for leaked in (secret, "Bearer", "do the thing", "sk-bbbb"):
            self.assertNotIn(leaked, dumped)
        self.assertIn("[redacted]", dumped)

    def test_distinct_redacted_identities_are_never_merged(self):
        rows = [rec("WU A", "started", "2026-11-03T10:00:00Z"), rec("WU B", "merged", "2026-11-03T11:00:00Z", outcome="merged", tokens=7)]
        report = self.report(rows)
        self.assertEqual([r["wu"] for r in report["work_units"]], ["[redacted-1]", "[redacted-2]"])
        for r in report["work_units"]:
            self.assertEqual(r["confidence"], "low")
            self.assertIsNone(r["latency_seconds"])
        self.assertEqual([r["tokens"] for r in report["work_units"]], [None, 7])

    def test_outcome_comes_from_chronologically_latest_end_event_regardless_of_order(self):
        base = [rec("WU-H", "started", "2026-11-03T10:00:00Z")]
        late = rec("WU-H", "merged", "2026-11-03T12:00:00Z", outcome="merged")
        early = rec("WU-H", "failed", "2026-11-03T11:00:00Z", outcome="failed")
        for order in ([late, early], [early, late]):
            h = self.row(self.report(base + order), "WU-H")
            self.assertEqual((h["outcome"], h["latency_seconds"], h["confidence"]), ("merged", 7200, "high"))
        tie = self.row(self.report(base + [late, rec("WU-H", "failed", "2026-11-03T12:00:00Z", outcome="failed")]), "WU-H")
        self.assertIsNone(tie["outcome"])
        self.assertEqual(tie["confidence"], "low")

    def test_non_list_input_is_rejected_and_junk_entries_do_not_crash(self):
        with self.assertRaises(ValueError):
            self.report({"wu": "x"})
        report = self.report([None, 5, "x"])
        self.assertFalse(report["zero_spend_ok"])
        self.assertEqual(self.row(report, "unknown")["confidence"], "low")

    def run_cli(self, receipts, *flags):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(receipts, handle)
        self.addCleanup(Path(handle.name).unlink)
        return subprocess.run([sys.executable, str(ROOT / "onecompany.py"), "outcome-report", "--receipts", handle.name, *flags],
                              capture_output=True, text=True, cwd=ROOT)

    def test_cli_exit_codes_and_read_only(self):
        before = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=ROOT).stdout
        ok = self.run_cli(GOOD, "--json")
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertTrue(json.loads(ok.stdout)["zero_spend_ok"])
        bad = self.run_cli([rec("WU-G", "started", "2026-11-03T10:00:00Z", "UNKNOWN_COST")])
        self.assertEqual(bad.returncode, 1)
        self.assertIn("VIOLATIONS=1", bad.stdout)
        after = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, cwd=ROOT).stdout
        self.assertEqual(before, after)
        broken = subprocess.run([sys.executable, str(ROOT / "onecompany.py"), "outcome-report", "--receipts", "/nonexistent.json"],
                                capture_output=True, text=True, cwd=ROOT)
        self.assertEqual(broken.returncode, 2)


class RollupTests(unittest.TestCase):
    RECEIPTS = [
        rec("WU-A", "started", "2026-11-03T10:00:00Z", worker="codex", pr=7),
        rec("WU-A", "incident", "2026-11-03T10:05:00Z", worker="codex", pr=7, tokens=10),
        rec("WU-B", "gate_pending", "2026-11-03T10:06:00Z", "HUMAN", worker="claude", pr="#8", tokens=5),
        rec("WU-B", "merged", "2026-11-03T10:07:00Z", worker="claude", pr="#8", tokens=7, outcome="merged"),
        rec("WU-C", "started", "2026-11-03T10:08:00Z"),
    ]

    def report(self, receipts):
        return orp.build_report(receipts, ALLOWED, FORBIDDEN)

    def test_rollups_group_by_worker_and_pr_and_sum_exactly(self):
        rep = self.report(self.RECEIPTS)
        by_w = {r["worker"]: r for r in rep["by_worker"]}
        self.assertEqual(by_w["codex"]["events"], 2)
        self.assertEqual(by_w["codex"]["incidents"], 1)
        self.assertEqual(by_w["codex"]["tokens"], 10)
        self.assertEqual(by_w["claude"]["pending_gates"], 1)
        self.assertEqual(by_w["claude"]["tokens"], 12)
        self.assertEqual({r["pr"] for r in rep["by_pr"]}, {"#7", "#8", "unattributed"})
        self.assertEqual(sum(r["events"] for r in rep["by_worker"]), rep["receipts"])
        self.assertEqual(sum(r["events"] for r in rep["by_pr"]), rep["receipts"])
        self.assertEqual(sum(r["incidents"] for r in rep["by_pr"]), sum(r["incidents"] for r in rep["work_units"]))

    def test_unattributed_receipts_are_separate_and_low_confidence(self):
        rep = self.report(self.RECEIPTS)
        un = next(r for r in rep["by_worker"] if r["worker"] == "unattributed")
        self.assertEqual((un["events"], un["confidence"], un["tokens"]), (1, "low", None))
        self.assertEqual(next(r for r in rep["by_worker"] if r["worker"] == "codex")["confidence"], "high")

    def test_bad_timestamp_lowers_group_confidence(self):
        rep = self.report([rec("WU-A", "started", "not-a-time", worker="codex")])
        self.assertEqual(rep["by_worker"][0]["confidence"], "low")

    def test_secret_like_worker_and_pr_are_redacted_and_not_merged(self):
        secret = "ghp_" + "a" * 30
        rep = self.report([rec("WU-A", "started", "2026-11-03T10:00:00Z", worker=secret, pr=secret),
                           rec("WU-A", "started", "2026-11-03T10:00:00Z", worker="bad worker!", pr="x y")])
        self.assertEqual({r["worker"] for r in rep["by_worker"]}, {"[redacted-1]", "[redacted-2]"})
        self.assertNotIn(secret, json.dumps(rep))

    def test_deterministic_and_junk_tolerant(self):
        self.assertEqual(json.dumps(self.report(self.RECEIPTS), sort_keys=True),
                         json.dumps(self.report(list(self.RECEIPTS)), sort_keys=True))
        rep = self.report([None, 5, {"pr": True, "worker": 3}])
        self.assertEqual(rep["by_pr"][0]["pr"], "unattributed")
        self.assertEqual(rep["by_worker"][0]["worker"], "unattributed")


if __name__ == "__main__":
    unittest.main()
