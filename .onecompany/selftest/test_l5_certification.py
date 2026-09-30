from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import l5_certification as cert


class L5CertificationTests(unittest.TestCase):
    def test_fault_drill_certifies_without_mutation(self):
        report = cert.certify()
        self.assertTrue(report["certified"])
        self.assertFalse(report["mutation_allowed"])
        self.assertGreaterEqual(len(report["cases"]), 17)
        self.assertRegex(report["report_sha256"], r"^[0-9a-f]{64}$")
        self.assertTrue(all(row["next_action"] for row in report["cases"]))

    def test_report_is_deterministic(self):
        first = cert.certify()
        second = cert.certify()
        self.assertEqual(first, second)
        self.assertEqual(copy.deepcopy(first), first)

    def test_required_faults_are_present(self):
        names = {row["name"] for row in cert.certify()["cases"]}
        required = {
            "ci-red-same-stream", "ci-transient-budget", "retry-exhaustion",
            "reviewer-outage", "self-review-rejected", "duplicate-stream",
            "stale-head", "moved-base", "emergency-stop", "human-only",
            "malformed-refs", "merged-unverified", "verified-ref-mismatch",
            "empty-ready-queue", "conflict-safe-selection", "lost-response-replay",
            "hold-preserves-budget",
        }
        self.assertTrue(required.issubset(names))


if __name__ == "__main__":
    unittest.main()
