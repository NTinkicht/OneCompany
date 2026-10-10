"""Safe offline Phase 2 shadow agreement regressions. No repo writes."""
from __future__ import annotations
import sys
from pathlib import Path
import unittest
import tempfile
from unittest.mock import patch
from contextlib import redirect_stdout
import io

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from l5_shadow_agreement import evaluate, strict_json_loads, read_bounded_evidence, main

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
        rows = [sample(i, f"2026-10-{10 + i // 34:02}", match=i < 95)
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
        low = [sample(i, f"2026-10-{10 + i // 34:02}", match=i < 94)
               for i in range(100)]
        self.assertFalse(evaluate(self.payload(low))["results"][REPO]["numerical_candidate"])

    def test_four_days_never_count_as_three_day_window(self):
        rows = [sample(i, f"2026-10-{10 + i // 25:02}") for i in range(100)]
        result = evaluate(self.payload(rows))["results"][REPO]
        self.assertEqual(result["distinct_days"], 4)
        self.assertFalse(result["numerical_candidate"])

    def test_run_identity_is_unique_across_repositories(self):
        initial = sample(5, "2026-10-10")
        copied = {**initial, "repository": "NTinkicht/veritas-atlas"}
        with self.assertRaisesRegex(ValueError, "SHADOW_DUPLICATE_RUN_ID"):
            evaluate(self.payload([initial, copied]))

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

    def test_unknown_but_matching_labels_do_not_inflate_agreement(self):
        records = [sample(i, f"2026-10-{10 + i:02}") for i in range(3)]
        records[0]["labeled_decision"] = "NOT_A_DECISION"
        records[0]["shadow_decision"] = "NOT_A_DECISION"
        with self.assertRaisesRegex(ValueError, "SHADOW_UNSUPPORTED_DECISION"):
            evaluate(self.payload(records))

    def test_nonstring_decisions_and_repo_fail_closed_without_traceback(self):
        for value in ([], {}, 0, None):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "SHADOW_UNSUPPORTED_DECISION"):
                    evaluate(self.payload([{**sample(1, "2026-10-10"),
                                            "labeled_decision": value}]))
                with self.assertRaisesRegex(ValueError, "SHADOW_TARGET_NOT_ALLOWED"):
                    evaluate(self.payload([{**sample(1, "2026-10-10"),
                                            "repository": value}]))

    def test_duplicate_raw_json_keys_rejected_before_scoring(self):
        for raw in (
            '{"schema":"L5_SHADOW_LABELS_V1","schema":"L5_SHADOW_LABELS_V1","records":[]}',
            '{"schema":"L5_SHADOW_LABELS_V1","records":[{"run_id":"a",'
            '"repository":"NTinkicht/OneCompany","day":"2026-10-10",'
            '"labeled_decision":"BLOCK","labeled_decision":"SELECT",'
            '"shadow_decision":"SELECT"}]}',
        ):
            with self.subTest(raw=raw), self.assertRaisesRegex(
                ValueError, "SHADOW_DUPLICATE_JSON_KEY"
            ):
                strict_json_loads(raw)

    def test_excessively_nested_json_is_invalid_evidence_without_traceback(self):
        # Real decoder recursion exhaustion must not escape to the CLI as
        # an unhandled exception or be mistaken for positive shadow proof.
        malicious = "[" * 10_000 + "0" + "]" * 10_000
        with self.assertRaisesRegex(ValueError, "SHADOW_JSON_NESTING_TOO_DEEP"):
            strict_json_loads(malicious)

    def test_oversized_input_is_refused_before_parser_and_cli_exits_two(self):
        # A tiny monkeypatched cap tests the real byte-boundary without
        # allocating an attacker-sized file in CI.
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "oversized.json"
            evidence.write_bytes(b" " * 17)
            with self.assertRaisesRegex(ValueError, "SHADOW_EVIDENCE_TOO_LARGE"):
                read_bounded_evidence(evidence, limit=16)
            output = io.StringIO()
            with patch("l5_shadow_agreement.MAX_EVIDENCE_BYTES", 16):
                # Function default expressions bind at definition time;
                # patch the bounded reader itself for the CLI path.
                with patch("l5_shadow_agreement.read_bounded_evidence",
                           side_effect=ValueError("SHADOW_EVIDENCE_TOO_LARGE")):
                    with patch.object(sys, "argv", ["shadow", str(evidence)]):
                        with redirect_stdout(output):
                            result = main()
            self.assertEqual(result, 2)
            self.assertIn('"status": "INVALID_EVIDENCE"', output.getvalue())
            self.assertIn("SHADOW_EVIDENCE_TOO_LARGE", output.getvalue())

    def test_empty_data_is_not_a_pass(self):
        result = evaluate(self.payload([]))
        self.assertIsNone(result["results"][REPO]["agreement_percent"])
        self.assertFalse(result["results"][REPO]["numerical_candidate"])


if __name__ == "__main__":
    unittest.main()
