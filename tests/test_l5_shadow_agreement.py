"""Safe offline Phase 2 shadow agreement regressions. No repo writes."""
from __future__ import annotations
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from l5_shadow_agreement import evaluate

REPO = "NTinkicht/OneCompany"


def sample(i, day, match=True):
    return {
        "run_id": f"run-{i}",
        "repository": REPO,
        "day": day,
        "labeled_decision": "SELECT",
        "shadow_decision": "SELECT" if match else "BLOCK",
    }


class ShadowAgreementTests(unittest.TestCase):
    def payload(self, rows):
        return {"schema": "L5_SHADOW_LABELS_V1", "records": rows}

    def test_three_days_exact_threshold_stays_uncertified(self):
        rows = [sample(i, f"2026-10-{10 + i // 20:02}", match=i < 95)
                for i in range(100)]
        value = evaluate(self.payload(rows))
        result = value["results"][REPO]
        self.assertEqual(result["agreement_percent"], 95.0)
        self.assertTrue(result["numerical_candidate"])
        self.assertFalse(value["production_l5_certified"])
        self.assertEqual(value["mutations"], 0)

    def test_two_days_or_below_threshold_refuse_candidate(self):
        short = [sample(i, f"2026-10-{10 + i // 50:02}") for i in range(100)]
        self.assertFalse(evaluate(self.payload(short))["results"][REPO]["numerical_candidate"])
        low = [sample(i, f"2026-10-{10 + i // 20:02}", match=i < 94)
               for i in range(100)]
        self.assertFalse(evaluate(self.payload(low))["results"][REPO]["numerical_candidate"])

    def test_duplicates_and_unknown_fields_fail_closed(self):
        row = sample(1, "2026-10-10")
        for records in ([row, row], [{**row, "authorization": "TOKEN"}],
                        [{**row, "repository": "other/repo"}]):
            with self.subTest(records=records):
                with self.assertRaises(ValueError):
                    evaluate(self.payload(records))

    def test_bad_calendar_and_missing_labels_rejected(self):
        for day in ("2026-02-30", "2026-10-1", "yesterday"):
            with self.subTest(day=day):
                with self.assertRaises(ValueError):
                    evaluate(self.payload([sample(1, day)]))
        with self.assertRaises(ValueError):
            evaluate(self.payload([{**sample(1, "2026-10-11"),
                                    "shadow_decision": ""}]))

    def test_empty_data_is_not_a_pass(self):
        result = evaluate(self.payload([]))
        self.assertIsNone(result["results"][REPO]["agreement_percent"])
        self.assertFalse(result["results"][REPO]["numerical_candidate"])


if __name__ == "__main__":
    unittest.main()
