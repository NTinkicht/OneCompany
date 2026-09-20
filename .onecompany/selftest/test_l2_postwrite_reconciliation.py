"""Regression for the real P3 ref-PATCH applied / response indeterminate race."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import l2_fixture_repair as repair

BASE = "a" * 40
INITIAL = "b" * 40
PROPOSED = "c" * 40
TARGET = "docs/onecompany-fixture/WU-C5.md"
BODY = "signed initial fixture\nRepair: complete\n"


def verify(api):
    return repair._confirm_published_repair(
        api, default="main", base=BASE,
        branch="onecompany-a4-wu-c5",
        number=9, repo="owner/pilot-c",
        proposed=PROPOSED, initial=INITIAL,
        target=TARGET, expected=BODY,
    )


class PostWriteReconciliationTests(unittest.TestCase):
    def test_stale_ref_read_then_exact_same_pr_write_is_confirmed(self):
        # The real job created the commit and ref but misclassified a transient
        # post-write read. Only the canonical ref and PR can prove convergence.
        api = Mock()
        with (
            patch.object(
                repair, "_api_branch",
                side_effect=[BASE, INITIAL, BASE, PROPOSED],
            ) as branch,
            patch.object(repair, "_head", return_value=PROPOSED) as head,
            patch.object(repair, "_check_repaired") as diff,
            patch.object(repair.time, "sleep") as pause,
        ):
            self.assertTrue(verify(api))
        self.assertEqual(branch.call_count, 4)
        head.assert_called_once()
        diff.assert_called_once_with(
            api, BASE, INITIAL, PROPOSED, TARGET, BODY,
        )
        pause.assert_called_once()

    def test_lost_ref_read_then_confirmed_exact_write_is_safe(self):
        api = Mock()
        with (
            patch.object(
                repair, "_api_branch",
                side_effect=[
                    repair.Refused("github_read_timed_out"),
                    BASE, PROPOSED,
                ],
            ),
            patch.object(repair, "_head", return_value=PROPOSED),
            patch.object(repair, "_check_repaired") as diff,
            patch.object(repair.time, "sleep"),
        ):
            self.assertTrue(verify(api))
            diff.assert_called_once()

    def test_foreign_head_never_qualifies_as_our_published_repair(self):
        api = Mock()
        with (
            patch.object(repair, "_api_branch",
                         side_effect=lambda api, branch:
                         BASE if branch == "main" else PROPOSED),
            patch.object(repair, "_head", return_value=INITIAL),
            patch.object(repair, "_check_repaired") as diff,
            patch.object(repair.time, "sleep") as pause,
        ):
            self.assertFalse(verify(api))
        diff.assert_not_called()
        self.assertEqual(pause.call_count, 4)

    def test_wrong_fixture_cannot_pass_even_when_both_heads_match(self):
        api = Mock()
        with (
            patch.object(repair, "_api_branch",
                         side_effect=[BASE, PROPOSED]),
            patch.object(repair, "_head", return_value=PROPOSED),
            patch.object(repair, "_check_repaired",
                         side_effect=repair.Refused("repair_fixture_mismatch")),
            patch.object(repair.time, "sleep") as pause,
        ):
            with self.assertRaisesRegex(
                repair.Refused, "repair_fixture_mismatch"
            ):
                verify(api)
            pause.assert_not_called()


if __name__ == "__main__":
    unittest.main()
