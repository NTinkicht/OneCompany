from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

SPEC = importlib.util.spec_from_file_location(
    "cutover_readiness", SCRIPTS / "cutover_readiness.py"
)
assert SPEC and SPEC.loader
cutover_readiness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cutover_readiness)

BASE_SPEC = importlib.util.spec_from_file_location(
    "test_cutover_readiness",
    ROOT / ".onecompany" / "selftest" / "test_cutover_readiness.py",
)
assert BASE_SPEC and BASE_SPEC.loader
base_tests = importlib.util.module_from_spec(BASE_SPEC)
BASE_SPEC.loader.exec_module(base_tests)


class SnapshotApprovalChronologyTests(unittest.TestCase):
    def test_human_approval_must_follow_observed_snapshot(self):
        manifest = base_tests.clean_manifest()
        manifest["snapshot"]["observed_at"] = "2026-09-18T01:05:00Z"
        manifest["cutover"]["human_gate"]["approved_at"] = (
            "2026-09-18T01:02:00Z"
        )

        report = cutover_readiness.analyze_cutover(manifest)

        self.assertFalse(report["cutover_ready"])
        self.assertIn(
            "HUMAN_CUTOVER_APPROVAL_MISSING",
            report["blocker_codes"],
        )


if __name__ == "__main__":
    unittest.main()
