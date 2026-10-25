"""OC-P0-01 (#359): read-only reconciliation of live pipeline branches."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from live_work_reconciliation import WorkSnapshot, branch_inconsistencies

SHA = "a" * 40


def snap(**overrides):
    fields = dict(
        main_sha=SHA,
        observed_main_sha=SHA,
        issue_ids=(1, 2, 3),
        next_ids=(2,),
        pr_issue_bindings=((9, 1),),
        active_lease_issue_ids=(1,),
        retired_pilot_issue_ids=(),
    )
    fields.update(overrides)
    return WorkSnapshot(**fields)


BASELINE = ("main", "ai/1-lease-store", "ai/3-docs", "claude/journal")


class BranchReconciliationTests(unittest.TestCase):
    def test_one_stream_per_known_issue_is_consistent(self):
        self.assertEqual(branch_inconsistencies(snap(), BASELINE), ())
        self.assertEqual(branch_inconsistencies(snap(), ()), ())

    def test_non_pipeline_branches_are_ignored(self):
        names = ("main", "feature/99-x", "claude/algeria-queue", "AI/99-x", "xai/99-x", "Ai/1-x")
        self.assertEqual(branch_inconsistencies(snap(), names), ())

    def test_stream_for_unknown_or_closed_issue_is_orphan(self):
        self.assertEqual(
            branch_inconsistencies(snap(), (*BASELINE, "ai/42-leftover")),
            (("ai/42-leftover", "ORPHAN_BRANCH"),),
        )

    def test_second_stream_for_one_issue_flags_every_stream(self):
        self.assertEqual(
            branch_inconsistencies(snap(), (*BASELINE, "ai/1-lease-store-v2")),
            (("ai/1-lease-store", "DUPLICATE_STREAM"),
             ("ai/1-lease-store-v2", "DUPLICATE_STREAM")),
        )

    def test_stream_for_retired_pilot_issue_is_reactivation(self):
        self.assertEqual(
            branch_inconsistencies(snap(retired_pilot_issue_ids=(3,)), BASELINE),
            (("ai/3-docs", "RETIRED_PILOT_REACTIVATED"),),
        )
        # A retired issue no longer in the open set is both.
        self.assertEqual(
            branch_inconsistencies(snap(retired_pilot_issue_ids=(128,)), ("ai/128-pilot-c",)),
            (("ai/128-pilot-c", "ORPHAN_BRANCH"),
             ("ai/128-pilot-c", "RETIRED_PILOT_REACTIVATED")),
        )

    def test_same_name_reported_twice(self):
        self.assertEqual(
            branch_inconsistencies(snap(), (*BASELINE, "ai/3-docs")),
            (("ai/3-docs", "DUPLICATE_BRANCH_OBSERVATION"),),
        )

    def test_malformed_pipeline_names_never_identify_an_issue(self):
        for bad in ("ai/", "ai/1", "ai/1-", "ai/-x", "ai/01-x", "ai/0-x", "ai/x-1",
                    "ai/1-x\n", "ai/1-x y", "ai/1-\u0000x", "ai/1--x", "ai/1-x/y",
                    "ai/١-x", "ai/1-é", "ai/+1-x"):
            with self.subTest(name=bad):
                # Issue 1 already has a stream: a malformed alias must not
                # count as a second one.
                self.assertEqual(
                    branch_inconsistencies(snap(), ("ai/1-lease-store", bad)),
                    ((bad, "INVALID_BRANCH_NAME"),),
                )

    def test_non_string_names_fail_closed(self):
        for bad in (None, 1, b"ai/1-x", ("ai/1-x",)):
            with self.subTest(name=bad):
                self.assertEqual(
                    branch_inconsistencies(snap(), ("ai/1-lease-store", bad)),
                    (("", "INVALID_BRANCH_NAME"),),
                )

    def test_bool_and_float_issue_ids_do_not_match_a_stream(self):
        for alias in (True, 1.0):
            with self.subTest(alias=alias):
                self.assertEqual(
                    branch_inconsistencies(snap(issue_ids=(alias, 2, 3)), ("ai/1-lease-store",)),
                    (("ai/1-lease-store", "ORPHAN_BRANCH"),),
                )
                self.assertEqual(
                    branch_inconsistencies(snap(retired_pilot_issue_ids=(alias,)), ("ai/1-lease-store",)),
                    (),
                )

    def test_a_single_name_string_is_refused(self):
        for bad in ("ai/1-lease-store", b"ai/1-lease-store"):
            with self.subTest(branches=bad):
                with self.assertRaises(TypeError):
                    branch_inconsistencies(snap(), bad)

    def test_findings_are_sorted_and_independent_of_input_order(self):
        names = ("ai/42-b", "main", "ai/2-x", "ai/01-bad", "ai/2-y", "ai/42-a", None)
        expected = (
            ("", "INVALID_BRANCH_NAME"),
            ("ai/01-bad", "INVALID_BRANCH_NAME"),
            ("ai/2-x", "DUPLICATE_STREAM"),
            ("ai/2-y", "DUPLICATE_STREAM"),
            ("ai/42-a", "DUPLICATE_STREAM"),
            ("ai/42-a", "ORPHAN_BRANCH"),
            ("ai/42-b", "DUPLICATE_STREAM"),
            ("ai/42-b", "ORPHAN_BRANCH"),
        )
        self.assertEqual(branch_inconsistencies(snap(), names), expected)
        self.assertEqual(branch_inconsistencies(snap(), tuple(reversed(names))), expected)
        self.assertEqual(branch_inconsistencies(snap(), list(names)), expected)


if __name__ == "__main__":
    unittest.main()
