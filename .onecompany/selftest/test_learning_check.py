import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def lesson(n, **over):
    l = {"id": f"L{n}", "status": "validated", "source_defects": [f"old{n}"], "evidence_refs": ["pr#1"]}
    l.update(over)
    return l


def defect(n, **over):
    d = {"id": f"h{n}", "held_out": True, "lesson": None, "recurred": False}
    d.update(over)
    return d


def base(**over):
    # Positive control: with a validated lesson 0/2 recurred, without 1/2 recurred.
    r = {"revision": "1" * 40, "lessons": [lesson(1)],
         "defects": [defect(1, lesson="L1"), defect(2, lesson="L1"),
                     defect(3, recurred=True), defect(4)]}
    r.update(over)
    return r


class LearningCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_cli(self, report, *extra, raw=None):
        path = self.tmp / "r.json"
        path.write_text(raw if raw is not None else json.dumps(report), encoding="utf-8")
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "learning_check.py"), str(path), *extra],
                              capture_output=True, text=True)

    def assert_fails(self, report, token):
        r = self.run_cli(report)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(token, r.stdout)

    def assert_unverifiable(self, report=None, raw=None):
        r = self.run_cli(report, raw=raw)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("UNABLE TO VERIFY", r.stderr)

    def test_clean_report_passes(self):
        r = self.run_cli(base())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads(self.run_cli(base(), "--json").stdout)["problems"], [])

    def test_validated_lesson_without_evidence_fails(self):
        self.assert_fails(base(lessons=[lesson(1, evidence_refs=[])]), "NO_EVIDENCE L1")

    def test_retired_lesson_without_evidence_is_not_flagged(self):
        r = self.run_cli(base(lessons=[lesson(1), lesson(2, status="retired", evidence_refs=[])]))
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_leaked_benchmark_fails(self):
        self.assert_fails(base(lessons=[lesson(1, source_defects=["h3"])]), "LEAKED_BENCHMARK L1 learned from held-out defect h3")

    def test_non_held_out_source_is_not_leakage(self):
        r = self.run_cli(base(defects=base()["defects"] + [defect(9, held_out=False)],
                              lessons=[lesson(1, source_defects=["h9"])]))
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_validated_lesson_recurrence_fails(self):
        d = base()["defects"]
        d[0]["recurred"] = True
        self.assert_fails(base(defects=d), "VALIDATED_LESSON_RECURRED h1 recurred despite L1")

    def test_falsified_and_retired_lessons_credited_are_stale(self):
        for status in ("falsified", "retired"):
            self.assert_fails(base(lessons=[lesson(1, status=status)]), f"STALE_LESSON_CREDITED h1 credits {status} lesson L1")

    def test_no_held_out_defects_fails(self):
        self.assert_fails(base(defects=[defect(1, held_out=False)]), "NO_HELD_OUT_BENCHMARK")

    def test_improvement_unmeasured_without_both_groups(self):
        self.assert_fails(base(defects=[defect(1, lesson="L1")]), "IMPROVEMENT_UNMEASURED")
        self.assert_fails(base(defects=[defect(1)]), "IMPROVEMENT_UNMEASURED")

    def test_no_improvement_fails(self):
        d = [defect(1, lesson="L1", recurred=True), defect(2, lesson="L1", recurred=True),
             defect(3, recurred=True), defect(4, recurred=True)]
        self.assert_fails(base(defects=d), "NO_IMPROVEMENT recurrence 2/2 with lesson vs 2/2 without")

    def test_worse_rate_with_lesson_fails_and_equal_rate_fails(self):
        d = [defect(1, lesson="L1"), defect(2, lesson="L1", recurred=True),
             defect(3), defect(4, recurred=True)]
        self.assert_fails(base(defects=d), "NO_IMPROVEMENT")

    def test_stale_credit_on_non_held_out_defect_fails(self):
        # Positive control: base() passes; only the non-held-out credit to a retired lesson differs.
        d = base()["defects"] + [defect(5, held_out=False, lesson="L2")]
        self.assertEqual(self.run_cli(base(lessons=[lesson(1), lesson(2)], defects=d)).returncode, 0)
        self.assert_fails(base(lessons=[lesson(1), lesson(2, status="retired")], defects=d),
                          "STALE_LESSON_CREDITED h5 credits retired lesson L2")

    def test_non_held_out_recurrence_with_validated_lesson_is_not_flagged(self):
        d = base()["defects"] + [defect(5, held_out=False, lesson="L1", recurred=True)]
        self.assertEqual(self.run_cli(base(defects=d)).returncode, 0)

    def test_missing_lesson_field_is_treated_as_null(self):
        d = base()["defects"]
        del d[3]["lesson"]
        r = self.run_cli(base(defects=d))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_malformed_input_is_unverifiable(self):
        self.assert_unverifiable(raw="not json")
        self.assert_unverifiable(raw="[]")
        self.assert_unverifiable(base(revision="abc"))
        for key in ("lessons", "defects"):
            r = base()
            del r[key]
            self.assert_unverifiable(r)
        self.assert_unverifiable(base(lessons=[lesson(1), lesson(1)]))
        self.assert_unverifiable(base(lessons=[lesson(1, status="current")]))
        self.assert_unverifiable(base(lessons=[lesson(1, evidence_refs="pr#1")]))
        self.assert_unverifiable(base(lessons=[lesson(1, source_defects=[1])]))
        self.assert_unverifiable(base(defects=[defect(1, lesson="nope")]))
        self.assert_unverifiable(base(defects=[defect(1, held_out="yes")]))
        self.assert_unverifiable(base(defects=[defect(1, recurred=1)]))
        for bad in ({}, [], 1):
            self.assert_unverifiable(base(defects=[defect(1, lesson=bad)]))


if __name__ == "__main__":
    unittest.main()
