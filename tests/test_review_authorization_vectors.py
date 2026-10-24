"""OC-P0-05 (#330): exact-head non-author review authorization vectors.

Drives the real ``review_authorization.authorize`` chain
(``latest_decisions`` -> ``review_platform_identity`` ->
``pull_request_material_author_actor_ids`` -> ``map_platform_login`` ->
``require_authority``) with only the GitHub transport and the base-trusted
identity-policy loader replaced by synthetic fixtures. No network is used.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import platform_identity  # noqa: E402
import review_authorization  # noqa: E402

REPO = "example/repo"
PR = 7
HEAD = "a" * 40
OLD_HEAD = "b" * 40
BASE = "c" * 40

POLICY = {
    "principals": [
        {"login": "writer", "actor_id": "actor:writer", "authorities": ["code_write"]},
        # Second platform login for the same actor (e.g. an app identity).
        {"login": "writer-app[bot]", "actor_id": "actor:writer", "authorities": ["code_review"]},
        {"login": "reviewer[bot]", "actor_id": "actor:reviewer", "authorities": ["code_review"]},
        {"login": "second-reviewer", "actor_id": "actor:second", "authorities": ["code_review"]},
        {"login": "observer", "actor_id": "actor:observer", "authorities": ["status_read"]},
    ]
}
PROVENANCE = {"source": "base", "blob_sha": "d" * 40, "trusted_ref": BASE}


def review(review_id: int, login: str, state: str, commit: str = HEAD, at: str | None = None) -> dict:
    return {
        "id": review_id,
        "user": {"login": login},
        "state": state,
        "commit_id": commit,
        "submitted_at": at or f"2026-10-24T09:{review_id:02d}:00Z",
    }


def commit(sha: str, login: str | None = "writer") -> dict:
    return {"sha": sha, "author": {"login": login} if login else None}


class Fixture:
    """Synthetic GitHub state; each attribute can be mutated per test."""

    def __init__(self) -> None:
        self.reviews: list[dict] = []
        self.commits: list[dict] = [commit("e" * 40), commit(HEAD)]
        self.reviews_outage = False
        self.review_detail_outage = False
        self.commits_outage = False
        self.policy_outage = False

    # review_authorization.gh_json: paginated review list
    def gh_json(self, path: str):
        if self.reviews_outage:
            raise RuntimeError("HTTP 502 from GitHub")
        assert path.startswith(f"repos/{REPO}/pulls/{PR}/reviews?"), path
        return [dict(item) for item in self.reviews] if path.endswith("page=1") else []

    # platform_identity._gh_json: single review detail
    def detail(self, path: str):
        if self.review_detail_outage:
            return None, "HTTP 503 from GitHub"
        review_id = int(path.rsplit("/", 1)[1])
        for item in self.reviews:
            if item["id"] == review_id:
                return dict(item), None
        return None, "not found"

    def paginated(self, path: str):
        if self.commits_outage:
            return None, "HTTP 500 from GitHub"
        assert path.startswith(f"repos/{REPO}/pulls/{PR}/commits"), path
        return [dict(item) for item in self.commits], None

    def policy(self, repo: str, trusted_ref: str):
        if self.policy_outage:
            return None, {"source": "base", "trusted_ref": trusted_ref}, ["base policy unavailable"]
        assert trusted_ref == BASE
        return POLICY, dict(PROVENANCE), []

    def authorize(self):
        with mock.patch.object(review_authorization, "gh_json", self.gh_json), \
                mock.patch.object(platform_identity, "_gh_json", self.detail), \
                mock.patch.object(platform_identity, "_gh_paginated_list", self.paginated), \
                mock.patch.object(platform_identity, "load_identity_policy", self.policy):
            return review_authorization.authorize(REPO, PR, HEAD, BASE)


class ReviewAuthorizationVectors(unittest.TestCase):
    def setUp(self) -> None:
        self.gh = Fixture()

    def assertDenied(self, reason_fragment: str | None = None) -> list[str]:
        ok, reasons = self.gh.authorize()
        self.assertFalse(ok, reasons)
        self.assertTrue(reasons, "a denial must carry a reason")
        if reason_fragment:
            self.assertTrue(any(reason_fragment in r for r in reasons), reasons)
        return reasons

    # ---- positive ------------------------------------------------------

    def test_trusted_non_author_exact_head_approval_authorizes(self):
        self.gh.reviews = [review(1, "reviewer[bot]", "APPROVED")]
        self.assertEqual(self.gh.authorize(), (True, []))

    def test_reviewer_login_matching_is_case_insensitive(self):
        self.gh.reviews = [review(1, "Reviewer[BOT]", "APPROVED")]
        self.assertEqual(self.gh.authorize(), (True, []))

    # ---- self-authorship ----------------------------------------------

    def test_material_author_cannot_approve_own_work(self):
        self.gh.reviews = [review(1, "writer", "APPROVED")]
        self.assertDenied("no trusted exact-head non-author approval")

    def test_alias_login_of_material_author_cannot_approve(self):
        # writer-app[bot] holds code_review but is the same actor as the author.
        self.gh.reviews = [review(1, "writer-app[bot]", "APPROVED")]
        self.assertDenied("no trusted exact-head non-author approval")

    def test_reviewer_who_authored_any_commit_on_head_is_excluded(self):
        self.gh.commits = [commit("e" * 40, "reviewer[bot]"), commit(HEAD, "writer")]
        self.gh.reviews = [review(1, "reviewer[bot]", "APPROVED")]
        self.assertDenied("no trusted exact-head non-author approval")

    def test_author_changes_requested_neither_blocks_nor_approves(self):
        self.gh.reviews = [review(1, "writer-app[bot]", "CHANGES_REQUESTED")]
        self.assertDenied("no trusted exact-head non-author approval")
        self.gh.reviews.append(review(2, "reviewer[bot]", "APPROVED"))
        self.assertEqual(self.gh.authorize(), (True, []))

    # ---- head change / stale decisions ---------------------------------

    def test_approval_on_previous_head_does_not_carry_over(self):
        self.gh.reviews = [review(1, "reviewer[bot]", "APPROVED", commit=OLD_HEAD)]
        self.assertDenied("no trusted exact-head non-author approval")

    def test_commit_list_not_bound_to_candidate_head_fails_closed(self):
        self.gh.commits = [commit("e" * 40), commit(OLD_HEAD)]
        self.gh.reviews = [review(1, "reviewer[bot]", "APPROVED")]
        self.assertDenied("not bound to the exact candidate head")

    def test_empty_commit_list_fails_closed(self):
        self.gh.commits = []
        self.gh.reviews = [review(1, "reviewer[bot]", "APPROVED")]
        self.assertDenied("no commits")

    def test_dismissal_after_approval_revokes_it(self):
        self.gh.reviews = [
            review(1, "reviewer[bot]", "APPROVED"),
            review(2, "reviewer[bot]", "DISMISSED"),
        ]
        self.assertDenied("no trusted exact-head non-author approval")

    def test_only_latest_decision_per_reviewer_counts(self):
        self.gh.reviews = [
            review(1, "reviewer[bot]", "CHANGES_REQUESTED"),
            review(2, "reviewer[bot]", "APPROVED"),
        ]
        self.assertEqual(self.gh.authorize(), (True, []))

    def test_commented_review_carries_no_authority(self):
        self.gh.reviews = [review(1, "reviewer[bot]", "COMMENTED")]
        self.assertDenied("no trusted exact-head non-author approval")

    def test_trusted_changes_requested_blocks_other_approval(self):
        self.gh.reviews = [
            review(1, "reviewer[bot]", "APPROVED"),
            review(2, "second-reviewer", "CHANGES_REQUESTED"),
        ]
        self.assertDenied("actor:second requested changes")

    # ---- reviewer identity ---------------------------------------------

    def test_unmapped_reviewer_has_no_authority(self):
        self.gh.reviews = [review(1, "stranger", "APPROVED")]
        self.assertDenied("no trusted exact-head non-author approval")

    def test_unmapped_reviewer_cannot_block_either(self):
        self.gh.reviews = [
            review(1, "reviewer[bot]", "APPROVED"),
            review(2, "stranger", "CHANGES_REQUESTED"),
        ]
        self.assertEqual(self.gh.authorize(), (True, []))

    def test_mapped_reviewer_without_code_review_authority_is_ignored(self):
        self.gh.reviews = [review(1, "observer", "APPROVED")]
        self.assertDenied("no trusted exact-head non-author approval")

    def test_review_with_invalid_id_is_ignored(self):
        bad = review(1, "reviewer[bot]", "APPROVED")
        bad["id"] = 0
        self.gh.reviews = [bad]
        self.assertDenied("no trusted exact-head non-author approval")

    # ---- authorship / outage -------------------------------------------

    def test_commit_without_platform_author_fails_closed(self):
        self.gh.commits = [commit("e" * 40, None), commit(HEAD)]
        self.gh.reviews = [review(1, "reviewer[bot]", "APPROVED")]
        self.assertDenied("no platform-resolved author login")

    def test_commit_by_unmapped_author_fails_closed(self):
        self.gh.commits = [commit("e" * 40, "ghost"), commit(HEAD)]
        self.gh.reviews = [review(1, "reviewer[bot]", "APPROVED")]
        self.assertDenied("'ghost' is unknown")

    def test_commit_listing_outage_fails_closed(self):
        self.gh.commits_outage = True
        self.gh.reviews = [review(1, "reviewer[bot]", "APPROVED")]
        self.assertDenied("HTTP 500")

    def test_identity_policy_outage_fails_closed(self):
        self.gh.policy_outage = True
        self.gh.reviews = [review(1, "reviewer[bot]", "APPROVED")]
        self.assertDenied("base policy unavailable")

    def test_review_detail_outage_grants_nothing(self):
        self.gh.review_detail_outage = True
        self.gh.reviews = [review(1, "reviewer[bot]", "APPROVED")]
        self.assertDenied("no trusted exact-head non-author approval")

    def test_review_list_outage_raises_instead_of_authorizing(self):
        self.gh.reviews_outage = True
        with self.assertRaises(RuntimeError):
            self.gh.authorize()

    def test_cli_exit_code_is_nonzero_when_denied(self):
        with mock.patch.object(review_authorization, "authorize", return_value=(False, ["x"])), \
                mock.patch.object(sys, "argv", ["review_authorization.py", "--repo", REPO,
                                                "--pr", str(PR), "--head", HEAD, "--base", BASE]), \
                mock.patch("builtins.print"):
            self.assertEqual(review_authorization.main(), 1)


class LatestDecisionsVectors(unittest.TestCase):
    def test_latest_by_submitted_at_then_id_per_lowercased_login(self):
        values = [
            review(5, "Rev", "APPROVED", at="2026-10-24T09:00:00Z"),
            review(3, "rev", "CHANGES_REQUESTED", at="2026-10-24T09:00:00Z"),
            review(9, "other", "COMMENTED"),
            {"id": 10, "user": None, "state": "APPROVED"},
        ]
        latest = review_authorization.latest_decisions(values)
        self.assertEqual([item["id"] for item in latest], [5])


if __name__ == "__main__":
    unittest.main()
