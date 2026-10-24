"""OC-P0-06 (#332): the final pre-merge coordination re-check.

``merge._final_coordination_check`` is the last reconciliation between
assurance verification and the GitHub merge mutation. Every other merge test
mocks it out; these vectors call the real function with its live readers
patched and pin that any drift refuses the merge without a partial success.
"""
from __future__ import annotations

import copy
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import merge

REPO = "NTinkicht/OneCompany"
PR = 7
HEAD = "a" * 40
BASE = "b" * 40
REVIEW_ID = 42
AUTHORS = {"implementer-example"}


def live() -> dict:
    return {
        "state": "OPEN",
        "isDraft": False,
        "headRefOid": HEAD,
        "baseRefOid": BASE,
        "baseRefName": "main",
    }


def lease(**overrides) -> dict:
    value = {
        "id": "L-WU900",
        "role": "implementation",
        "actor": "implementer-example",
        "work_unit": "WU900",
        "pr": PR,
        "status": "active",
    }
    value.update(overrides)
    return value


def gate(**overrides) -> dict:
    value = {
        "verdict": "PASS — MERGE_READY",
        "stale": False,
        "sha": HEAD,
        "base_sha": BASE,
        "review_id": REVIEW_ID,
        "material_authors": sorted(AUTHORS),
    }
    value.update(overrides)
    return value


def view(**overrides) -> dict:
    value = {
        "active_leases": [lease()],
        "material_authors": sorted(AUTHORS),
        "current_gate": gate(),
    }
    value.update(overrides)
    return value


REVIEWER = {"actor_id": "ntk-reviewer", "authorities": ["code_review"]}


class FinalCoordinationCheckTests(unittest.TestCase):
    def run_check(
        self,
        *,
        live_result=None,
        protected_result=None,
        view_result=None,
        view_error: Exception | None = None,
        platform_result=None,
        reviewer_result=None,
    ):
        live_result = (live(), None) if live_result is None else live_result
        protected_result = (
            ({"branch": "main"}, []) if protected_result is None else protected_result
        )
        view_value = view() if view_result is None else view_result
        platform_result = (
            (set(AUTHORS), []) if platform_result is None else platform_result
        )
        reviewer_result = (
            (dict(REVIEWER), []) if reviewer_result is None else reviewer_result
        )
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(merge, "live_pr", return_value=live_result)
            )
            self.protected = stack.enter_context(
                patch.object(
                    merge,
                    "protected_default_branch_context",
                    return_value=protected_result,
                )
            )
            if view_error is not None:
                stack.enter_context(
                    patch.object(merge, "coordination_view", side_effect=view_error)
                )
            else:
                stack.enter_context(
                    patch.object(
                        merge,
                        "coordination_view",
                        return_value=copy.deepcopy(view_value),
                    )
                )
            stack.enter_context(
                patch.object(merge, "_platform_authors", return_value=platform_result)
            )
            self.reviewer = stack.enter_context(
                patch.object(merge, "_verify_reviewer", return_value=reviewer_result)
            )
            return merge._final_coordination_check(
                REPO, PR, HEAD, BASE, REVIEW_ID, set(AUTHORS)
            )

    def assert_refused(self, result, fragment: str) -> None:
        active, errors = result
        self.assertIsNone(active, "a refused final check must not return a lease")
        self.assertTrue(errors, "a refused final check must explain itself")
        self.assertTrue(
            any(fragment in error for error in errors),
            f"expected an error containing {fragment!r}, got {errors!r}",
        )

    def test_consistent_state_returns_the_active_implementation_lease(self):
        active, errors = self.run_check()
        self.assertEqual(errors, [])
        self.assertEqual(active, [lease()])
        # The reviewer is re-verified against the exact approved revision.
        self.reviewer.assert_called_once_with(
            REPO, PR, HEAD, BASE, REVIEW_ID, AUTHORS
        )
        self.protected.assert_called_once_with(REPO, BASE, claimed_branch="main")

    def test_live_pr_reread_failure_refuses(self):
        self.assert_refused(
            self.run_check(live_result=(None, "HTTP 502")),
            "cannot re-read live PR",
        )

    def test_closed_or_draft_pr_refuses(self):
        for change in ({"state": "CLOSED"}, {"state": "MERGED"}, {"isDraft": True}):
            with self.subTest(change=change):
                value = live()
                value.update(change)
                self.assert_refused(
                    self.run_check(live_result=(value, None)),
                    "ceased to be open/ready",
                )

    def test_head_change_after_verification_refuses(self):
        value = live()
        value["headRefOid"] = "c" * 40
        self.assert_refused(
            self.run_check(live_result=(value, None)), "PR head changed"
        )

    def test_base_drift_or_branch_behind_refuses(self):
        value = live()
        value["baseRefOid"] = "d" * 40
        self.assert_refused(
            self.run_check(live_result=(value, None)), "PR base changed"
        )

    def test_unprotected_or_unverifiable_base_branch_refuses(self):
        self.assert_refused(
            self.run_check(protected_result=(None, ["base branch is not protected"])),
            "base branch is not protected",
        )

    def test_coordination_view_failure_refuses(self):
        self.assert_refused(
            self.run_check(view_error=RuntimeError("ledger unreadable")),
            "cannot re-read coordination authority",
        )

    def test_lost_or_foreign_implementation_lease_refuses(self):
        for leases in (
            [],
            [lease(pr=PR + 1)],
            [lease(role="review")],
        ):
            with self.subTest(leases=leases):
                self.assert_refused(
                    self.run_check(view_result=view(active_leases=leases)),
                    "implementation lease expired/transferred",
                )

    def test_changed_material_authorship_refuses(self):
        changed = sorted(AUTHORS | {"second-author"})
        self.assert_refused(
            self.run_check(
                view_result=view(
                    material_authors=changed,
                    current_gate=gate(material_authors=changed),
                ),
                platform_result=(set(changed), []),
            ),
            "material authorship changed",
        )

    def test_new_unreconciled_platform_author_refuses(self):
        self.assert_refused(
            self.run_check(platform_result=(AUTHORS | {"late-pusher"}, [])),
            "new/unreconciled platform material author",
        )

    def test_platform_author_lookup_failure_refuses(self):
        self.assert_refused(
            self.run_check(platform_result=(None, ["cannot list PR commits"])),
            "cannot list PR commits",
        )

    def test_stale_or_mismatched_gate_refuses(self):
        for current in (
            None,
            gate(verdict="CHANGES_REQUIRED"),
            gate(stale=True),
            gate(sha="e" * 40),
            gate(base_sha="f" * 40),
            gate(review_id=REVIEW_ID + 1),
            gate(material_authors=["someone-else"]),
        ):
            with self.subTest(gate=current):
                self.assert_refused(
                    self.run_check(view_result=view(current_gate=current)),
                    "binding coordination gate changed or became stale",
                )

    def test_reviewer_no_longer_independent_refuses(self):
        self.assert_refused(
            self.run_check(reviewer_result=(None, ["reviewer is a material author"])),
            "reviewer independence changed before merge",
        )

    def test_every_drift_is_reported_together(self):
        value = live()
        value["headRefOid"] = "c" * 40
        value["baseRefOid"] = "d" * 40
        active, errors = self.run_check(
            live_result=(value, None),
            view_result=view(active_leases=[], current_gate=gate(stale=True)),
            reviewer_result=(None, ["review dismissed"]),
        )
        self.assertIsNone(active)
        for fragment in (
            "PR head changed",
            "PR base changed",
            "implementation lease expired/transferred",
            "binding coordination gate changed or became stale",
            "reviewer independence changed",
        ):
            self.assertTrue(any(fragment in error for error in errors), fragment)


if __name__ == "__main__":
    unittest.main()
