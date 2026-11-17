from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from autonomy_guard import continuous_selection_violations, level_violations

INVALID = ["autonomy_level_invalid_or_unverified"]
MUTATING = ("implementation", "ci_remediation", "merge_execution")


def cfg(level: object, **extra: object) -> dict:
    return {"autonomy": {"level": level, **extra}}


class MalformedAutonomyLevelTests(unittest.TestCase):
    def test_non_string_or_unknown_levels_are_refused_not_raised(self) -> None:
        for level in (["L5"], {"a": 1}, None, 5, True, "l5", "L99", ""):
            for capability in MUTATING:
                with self.subTest(level=level, capability=capability):
                    self.assertEqual(level_violations(cfg(level), capability, unattended=True), INVALID)

    def test_continuous_selection_refuses_malformed_level(self) -> None:
        for level in (["L4"], {"L4": 1}, None, 4):
            with self.subTest(level=level):
                self.assertEqual(continuous_selection_violations(cfg(level, continue_when_ready_work_exists=True)), INVALID)

    def test_non_dict_autonomy_is_unavailable(self) -> None:
        for autonomy in (None, "L5", ["L5"], 5):
            with self.subTest(autonomy=autonomy):
                self.assertEqual(level_violations({"autonomy": autonomy}, "implementation", unattended=True), ["autonomy_policy_unavailable"])

    def test_valid_levels_unchanged(self) -> None:
        self.assertEqual(level_violations(cfg("L2"), "implementation", unattended=True), [])
        self.assertEqual(level_violations(cfg("L3"), "merge_execution", unattended=True), [])
        self.assertEqual(continuous_selection_violations(cfg("L4", continue_when_ready_work_exists=True)), [])


if __name__ == "__main__":
    unittest.main()
