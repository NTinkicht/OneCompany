"""OC-P0-01 (#361): reconcile recorded failed/unknown writes before replay."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from live_work_reconciliation import WorkSnapshot, WriteAttempt, replay_inconsistencies

SHA = "a" * 40
OTHER = "b" * 40


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


def att(**overrides):
    fields = dict(operation_id="op-1", issue=1, outcome="success", readback="present")
    fields.update(overrides)
    return WriteAttempt(**fields)


def safe_retry(**overrides):
    fields = dict(outcome="failure", readback="absent", retries=1, safety_rejected=True,
                  expected_head_sha=SHA, observed_head_sha=SHA)
    fields.update(overrides)
    return att(**fields)


def check(*attempts, snapshot=None):
    return replay_inconsistencies(snapshot or snap(), attempts)


class ReplayReconciliationTests(unittest.TestCase):
    def test_verified_success_and_single_safe_retry_are_consistent(self):
        self.assertEqual(check(), ())
        self.assertEqual(check(att()), ())
        self.assertEqual(check(att(outcome="success", readback=None)), ())
        self.assertEqual(check(safe_retry()), ())
        self.assertEqual(check(safe_retry(outcome="unknown")), ())
        # A failure confirmed absent with no retry yet is simply recorded.
        self.assertEqual(check(att(outcome="failure", readback="absent")), ())

    def test_unknown_or_failed_outcome_without_readback_is_unverified(self):
        for outcome in ("failure", "unknown"):
            with self.subTest(outcome=outcome):
                self.assertEqual(check(att(outcome=outcome, readback=None)),
                                 (("op-1", "UNVERIFIED_OUTCOME"),))

    def test_recorded_success_with_absent_effect_is_unverified(self):
        self.assertEqual(check(att(outcome="success", readback="absent")),
                         (("op-1", "UNVERIFIED_OUTCOME"),))

    def test_existing_side_effect_must_not_be_repeated(self):
        # commit-created-but-response-lost: the effect exists, record success.
        for outcome in ("failure", "unknown"):
            with self.subTest(outcome=outcome):
                self.assertEqual(check(att(outcome=outcome, readback="present")),
                                 (("op-1", "RETRY_WOULD_DUPLICATE"),))

    def test_retry_without_absent_readback_and_safety_rejection_is_unsafe(self):
        cases = (
            dict(readback=None, outcome="unknown"),
            dict(readback="present"),
            dict(safety_rejected=False),
            dict(safety_rejected="yes"),
            dict(safety_rejected=1),
        )
        for overrides in cases:
            with self.subTest(**{k: repr(v) for k, v in overrides.items()}):
                self.assertIn(("op-1", "UNSAFE_RETRY"), check(safe_retry(**overrides)))

    def test_unknown_outcome_blind_retry_reports_every_finding(self):
        self.assertEqual(
            check(safe_retry(outcome="unknown", readback=None, safety_rejected=False)),
            (("op-1", "UNSAFE_RETRY"), ("op-1", "UNVERIFIED_OUTCOME")),
        )

    def test_at_most_one_retry(self):
        self.assertEqual(check(safe_retry(retries=2)), (("op-1", "RETRY_LIMIT_EXCEEDED"),))

    def test_retry_on_moved_or_unproven_head_is_stale(self):
        for expected, observed in ((SHA, OTHER), (None, SHA), (SHA, None), (None, None),
                                   ("A" * 40, "A" * 40), ("", "")):
            with self.subTest(expected=expected, observed=observed):
                self.assertEqual(check(safe_retry(expected_head_sha=expected,
                                                  observed_head_sha=observed)),
                                 (("op-1", "STALE_REPLAY"),))

    def test_head_is_only_judged_for_a_retry(self):
        self.assertEqual(check(att(expected_head_sha=SHA, observed_head_sha=OTHER)), ())

    def test_duplicate_operation_id(self):
        self.assertEqual(check(att(), att(issue=2)), (("op-1", "DUPLICATE_OPERATION"),))

    def test_orphan_and_retired_pilot_replay(self):
        self.assertEqual(check(att(issue=42)), (("op-1", "ORPHAN_REPLAY"),))
        self.assertEqual(check(att(issue=3), snapshot=snap(retired_pilot_issue_ids=(3,))),
                         (("op-1", "RETIRED_PILOT_REACTIVATED"),))

    def test_invalid_identities(self):
        for op in ("", "   ", None, 7):
            with self.subTest(op=op):
                self.assertEqual(check(att(operation_id=op)), (("", "INVALID_OPERATION_ID"),))
        for issue in (True, 1.0, 0, -1, "1"):
            with self.subTest(issue=issue):
                # Never aliased to a known issue nor reported as orphan.
                self.assertEqual(check(att(issue=issue)), (("op-1", "INVALID_ISSUE_ID"),))

    def test_invalid_outcome_readback_and_retry_count(self):
        for outcome in ("SUCCESS", "ok", None, ""):
            with self.subTest(outcome=outcome):
                self.assertEqual(check(att(outcome=outcome)), (("op-1", "INVALID_OUTCOME"),))
        for readback in ("Present", "", "missing", True):
            with self.subTest(readback=readback):
                self.assertEqual(check(att(readback=readback)), (("op-1", "INVALID_READBACK"),))
        for retries in (-1, True, 1.0, "1", None):
            with self.subTest(retries=retries):
                self.assertEqual(check(att(retries=retries)), (("op-1", "INVALID_RETRY_COUNT"),))

    def test_invalid_readback_never_permits_a_retry(self):
        self.assertEqual(check(safe_retry(readback="ABSENT")),
                         (("op-1", "INVALID_READBACK"), ("op-1", "UNSAFE_RETRY")))

    def test_completed_retry_is_judged_on_pre_retry_readback(self):
        # Codex P2 on #362: a permitted retry that succeeded now reads back
        # ``present``; its safety evidence is the readback before the retry.
        done = safe_retry(outcome="success", readback="present", pre_retry_readback="absent")
        self.assertEqual(check(done), ())
        # Without pre-retry evidence a present effect plus a retry stays unsafe.
        self.assertEqual(check(safe_retry(outcome="success", readback="present")),
                         (("op-1", "UNSAFE_RETRY"),))
        # Pre-retry evidence that the effect existed never permits the retry.
        self.assertEqual(
            check(safe_retry(outcome="success", readback="present", pre_retry_readback="present")),
            (("op-1", "UNSAFE_RETRY"),))
        # The safety rejection, limit and head rules still apply to it.
        self.assertIn(("op-1", "UNSAFE_RETRY"),
                      check(safe_retry(outcome="success", readback="present",
                                       pre_retry_readback="absent", safety_rejected=False)))
        self.assertIn(("op-1", "RETRY_LIMIT_EXCEEDED"),
                      check(safe_retry(readback="present", outcome="success",
                                       pre_retry_readback="absent", retries=2)))
        self.assertIn(("op-1", "STALE_REPLAY"),
                      check(safe_retry(readback="present", outcome="success",
                                       pre_retry_readback="absent", observed_head_sha=OTHER)))

    def test_invalid_pre_retry_readback_never_permits_a_retry(self):
        self.assertEqual(
            check(safe_retry(pre_retry_readback="gone")),
            (("op-1", "INVALID_READBACK"), ("op-1", "UNSAFE_RETRY")))

    def test_findings_are_sorted_and_stable(self):
        attempts = (att(operation_id="z", issue=42, outcome="unknown", readback=None),
                    att(operation_id="a", outcome="failure", readback="present"))
        first = replay_inconsistencies(snap(), attempts)
        self.assertEqual(first, tuple(sorted(first)))
        self.assertEqual(first, replay_inconsistencies(snap(), tuple(reversed(attempts))))
        self.assertEqual(first, (("a", "RETRY_WOULD_DUPLICATE"), ("z", "ORPHAN_REPLAY"),
                                 ("z", "UNVERIFIED_OUTCOME")))

    def test_rejects_non_collection_input(self):
        for bad in ("op-1", b"op-1", None, att()):
            with self.subTest(bad=bad):
                with self.assertRaises(TypeError):
                    replay_inconsistencies(snap(), bad)


if __name__ == "__main__":
    unittest.main()
