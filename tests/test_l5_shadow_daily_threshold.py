"""Real evaluate() integration tests for per-day 95% gate (not a stub)."""
from __future__ import annotations
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from l5_shadow_agreement import evaluate

REPO = "NTinkicht/OneCompany"
DAYS = ("2026-10-10", "2026-10-11", "2026-10-12")


def rows(spec, repo=REPO, start=0):
    """Each (count, matches) pair becomes deterministic valid input rows."""
    out = []
    for day, (total, matched) in zip(DAYS, spec):
        for i in range(total):
            out.append({"run_id": f"run-{start + len(out)}", "repository": repo,
                        "day": day, "labeled_decision": "SELECT",
                        "shadow_decision": "SELECT" if i < matched else "BLOCK"})
    return out


def report(spec, repo=REPO):
    return evaluate({"schema": "L5_SHADOW_LABELS_V1", "records": rows(spec, repo)})


class DailyThresholdIntegrationTests(unittest.TestCase):
    def test_pooled_99_percent_cannot_hide_day_two_zero(self):
        v = report([(98, 98), (1, 0), (1, 1)])
        s = v["results"][REPO]
        self.assertEqual(s["agreement_percent"], 99.0)
        self.assertTrue(s["consecutive_three_day_window"])
        self.assertFalse(s["daily_threshold_met"])
        self.assertFalse(s["numerical_candidate"])
        self.assertFalse(v["production_l5_certified"])

    def test_exact_95_each_day_is_numerical_candidate_only(self):
        s = report([(20, 19), (40, 38), (60, 57)])["results"][REPO]
        self.assertTrue(s["daily_threshold_met"])
        self.assertEqual(s["agreement_percent"], 95.0)
        self.assertTrue(s["numerical_candidate"])

    def test_949_percent_one_day_rejected_despite_good_pool(self):
        s = report([(1000, 1000), (1000, 1000), (1000, 949)])["results"][REPO]
        self.assertFalse(s["daily_threshold_met"])
        self.assertFalse(s["numerical_candidate"])

    def test_95_percent_boundary_integer_no_float_rounding(self):
        s = report([(20, 19), (20, 19), (2000, 1899)])["results"][REPO]
        self.assertFalse(s["daily_threshold_met"])
        self.assertFalse(s["numerical_candidate"])

    def test_no_data_fails_closed(self):
        s = report([])["results"][REPO]
        self.assertFalse(s["daily_threshold_met"])
        self.assertFalse(s["numerical_candidate"])

    def test_two_days_cannot_qualify_even_when_each_perfect(self):
        s = report([(1, 1), (1, 1)])["results"][REPO]
        self.assertFalse(s["daily_threshold_met"])
        self.assertFalse(s["numerical_candidate"])

    def test_single_day_mismatch_blocks_independent_repo_only(self):
        one = rows([(20, 19), (20, 19), (20, 19)], start=0)
        tab = rows([(100, 100), (1, 0), (1, 1)], repo="NTinkicht/Tabibi", start=100)
        values = evaluate({"schema": "L5_SHADOW_LABELS_V1", "records": one + tab})["results"]
        self.assertTrue(values[REPO]["numerical_candidate"])
        self.assertFalse(values["NTinkicht/Tabibi"]["numerical_candidate"])

    def test_100000_rows_per_day_gate(self):
        s = report([(33334, 33334), (33333, 33333), (33333, 31666)])["results"][REPO]
        self.assertFalse(s["daily_threshold_met"])
        self.assertFalse(s["numerical_candidate"])

    def test_output_never_certifies_production(self):
        v = report([(1, 1), (1, 1), (1, 1)])
        self.assertFalse(v["production_l5_certified"])
        self.assertEqual(v["mode"], "READ_ONLY")
        self.assertEqual(v["mutations"], 0)


if __name__ == "__main__":
    unittest.main()
