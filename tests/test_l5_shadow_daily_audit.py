"""Security-positive daily auditability tests for L5 Phase 2 evaluator."""
from __future__ import annotations
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from l5_shadow_agreement import evaluate

REPO = "NTinkicht/OneCompany"
DAYS = ("2026-10-10", "2026-10-11", "2026-10-12")

def payload(spec, repo=REPO):
    records=[]
    for day, (count, matches) in zip(DAYS, spec):
        for i in range(count):
            records.append({"run_id": f"r-{len(records)}", "repository": repo,
                            "day": day, "labeled_decision": "SELECT",
                            "shadow_decision": "SELECT" if i < matches else "BLOCK"})
    return {"schema": "L5_SHADOW_LABELS_V1", "records": records}

class DailyAuditTests(unittest.TestCase):
    def test_aggregate_99_percent_cannot_hide_zero_percent_day(self):
        v=evaluate(payload([(98,98),(1,0),(1,1)]))
        s=v["results"][REPO]
        self.assertEqual(s["agreement_percent"],99.0)
        self.assertFalse(s["daily_threshold_met"])
        self.assertFalse(s["numerical_candidate"])
        self.assertEqual(s["daily_agreement"][DAYS[1]], {
            "samples":1,"matching":0,"agreement_percent":0.0,"threshold_met":False})
        self.assertFalse(v["production_l5_certified"])

    def test_each_day_exactly_95_percent(self):
        s=evaluate(payload([(20,19),(40,38),(60,57)]))["results"][REPO]
        self.assertTrue(s["numerical_candidate"])
        self.assertEqual(list(s["daily_agreement"]),list(DAYS))
        for day in DAYS:
            self.assertEqual(s["daily_agreement"][day]["agreement_percent"],95.0)
            self.assertTrue(s["daily_agreement"][day]["threshold_met"])

    def test_rounding_does_not_change_threshold(self):
        s=evaluate(payload([(20,19),(20,19),(2000,1899)]))["results"][REPO]
        self.assertEqual(s["daily_agreement"][DAYS[2]]["agreement_percent"],94.95)
        self.assertFalse(s["daily_agreement"][DAYS[2]]["threshold_met"])
        self.assertFalse(s["numerical_candidate"])

    def test_empty_evidence_is_not_a_candidate(self):
        s=evaluate(payload([]))["results"][REPO]
        self.assertEqual(s["daily_agreement"],{})
        self.assertFalse(s["daily_threshold_met"])
        self.assertFalse(s["numerical_candidate"])

    def test_two_days_cannot_be_a_candidate(self):
        s=evaluate(payload([(1,1),(1,1)]))["results"][REPO]
        self.assertEqual(len(s["daily_agreement"]),2)
        self.assertFalse(s["numerical_candidate"])

    def test_no_individual_labels_in_daily_summary(self):
        s=evaluate(payload([(20,19),(20,19),(20,19)]))["results"][REPO]
        for summary in s["daily_agreement"].values():
            self.assertEqual(set(summary),{"samples","matching","agreement_percent","threshold_met"})

if __name__=="__main__": unittest.main()
