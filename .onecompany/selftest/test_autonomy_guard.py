from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import dispatch
from autonomy_guard import continuous_selection_violations, level_violations


def policy(level: str, *, continue_work: bool = False) -> dict:
    return {
        "autonomy": {
            "level": level,
            "continue_when_ready_work_exists": continue_work,
        }
    }


class UnattendedAutonomyBoundaryTests(unittest.TestCase):
    def test_assisted_level_never_grants_unattended_mutation(self) -> None:
        for capability in ("implementation", "ci_remediation", "merge_execution"):
            with self.subTest(capability=capability):
                self.assertTrue(
                    level_violations(policy("L1"), capability, unattended=True)
                )

    def test_readonly_automation_is_not_blocked_by_implementation_floor(self) -> None:
        self.assertEqual(
            level_violations(
                policy("L1"), "repository_intelligence", unattended=True
            ),
            [],
        )

    def test_l2_grants_bounded_implementation_but_not_unattended_merge(self) -> None:
        self.assertEqual(
            level_violations(policy("L2"), "implementation", unattended=True),
            [],
        )
        self.assertEqual(
            level_violations(policy("L2"), "ci_remediation", unattended=True),
            [],
        )
        self.assertIn(
            "unattended_merge_requires_approved_L3",
            level_violations(policy("L2"), "merge_execution", unattended=True),
        )

    def test_l3_allows_merge_but_not_continuous_wu_selection(self) -> None:
        self.assertEqual(
            level_violations(policy("L3"), "merge_execution", unattended=True),
            [],
        )
        self.assertIn(
            "continuous_work_selection_requires_approved_L4",
            continuous_selection_violations(policy("L3", continue_work=True)),
        )

    def test_l4_still_respects_explicit_continuous_switch(self) -> None:
        self.assertIn(
            "continuous_work_selection_disabled",
            continuous_selection_violations(policy("L4")),
        )
        self.assertEqual(
            continuous_selection_violations(policy("L4", continue_work=True)),
            [],
        )

    def test_unavailable_or_invalid_policy_fails_closed(self) -> None:
        self.assertTrue(level_violations({}, "implementation", unattended=True))
        self.assertTrue(
            level_violations(policy("L99"), "implementation", unattended=True)
        )

    def test_actual_dispatch_blocks_l1_unattended_implementation(self) -> None:
        # The source product is L1: missing actor/lease capacity must not mask
        # the additional explicit autonomy-boundary denial.
        with patch.object(dispatch, "emergency_stop_active", return_value=False):
            result = dispatch.resolve_dispatch(
                "onecompany-local",
                "implementation",
                unattended=True,
                lease_id="synthetic-non-authoritative-lease",
            )
        self.assertEqual(result["status"], "CAPACITY_BLOCKED")
        self.assertIn(
            "unattended_implementation_requires_approved_L2",
            result["reasons"],
        )


if __name__ == "__main__":
    unittest.main()
