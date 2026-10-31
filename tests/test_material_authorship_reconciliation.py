"""OC-P0-01 (#373): fail-closed material authorship from the exact-head commit list."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from live_work_reconciliation import (  # noqa: E402
    PullRequestObservation, WorkSnapshot, pr_inconsistencies,
)
from material_authorship_reconciliation import (  # noqa: E402
    COMMIT_LIST_CAP, CommitObservation, derive_material_authors,
)

MAIN = "a" * 40
FIRST = "1" * 40
SECOND = "2" * 40
HEAD = "c" * 40
BOT = "ntk-reviewer[bot]"


def commit(sha, author="NTinkicht", committer="NTinkicht", message="change\n\nMaterial-Author: claude"):
    return CommitObservation(sha, author, committer, message)


class MaterialAuthorshipTests(unittest.TestCase):
    def assertWithheld(self, result, findings):
        self.assertEqual((), result.authors)
        self.assertEqual(findings, result.findings)

    def test_authors_committers_and_trailers_are_unioned_and_sorted(self):
        result = derive_material_authors((
            commit(FIRST, author="alice", committer="web-flow", message="a\n\nMaterial-Author: codex"),
            commit(HEAD, author="NTinkicht", committer="NTinkicht",
                   message="b\n\nmaterial-author:  claude \nCo-Authored-By: x <x@example.com>"),
        ), HEAD)
        self.assertEqual(("NTinkicht", "alice", "claude", "codex", "web-flow"), result.authors)
        self.assertEqual((), result.findings)

    def test_commit_without_trailer_contributes_its_logins(self):
        result = derive_material_authors((commit(HEAD, message="plain"),), HEAD)
        self.assertEqual(("NTinkicht",), result.authors)

    def test_no_commits_withholds(self):
        self.assertWithheld(derive_material_authors((), HEAD), (("", "NO_COMMITS"),))

    def test_last_commit_must_be_exact_head(self):
        result = derive_material_authors((commit(HEAD), commit(SECOND)), HEAD)
        self.assertWithheld(result, (("", "HEAD_NOT_LAST_COMMIT"),))

    def test_head_absent_from_stale_list_withholds(self):
        result = derive_material_authors((commit(FIRST), commit(SECOND)), HEAD)
        self.assertWithheld(result, (("", "HEAD_NOT_LAST_COMMIT"),))

    def test_unlinked_author_withholds(self):
        result = derive_material_authors((commit(FIRST, author=None), commit(HEAD)), HEAD)
        self.assertWithheld(result, ((FIRST, "UNATTRIBUTED_COMMIT"),))

    def test_unlinked_or_blank_committer_withholds(self):
        for committer in (None, "", " NTinkicht"):
            with self.subTest(committer=committer):
                result = derive_material_authors((commit(HEAD, committer=committer),), HEAD)
                self.assertWithheld(result, ((HEAD, "UNATTRIBUTED_COMMIT"),))

    def test_empty_material_author_trailer_withholds(self):
        result = derive_material_authors((commit(HEAD, message="x\n\nMaterial-Author:   "),), HEAD)
        self.assertWithheld(result, ((HEAD, "INVALID_MATERIAL_AUTHOR_TRAILER"),))

    def test_duplicate_commit_withholds(self):
        result = derive_material_authors((commit(HEAD), commit(HEAD)), HEAD)
        self.assertWithheld(result, ((HEAD, "DUPLICATE_COMMIT"),))

    def test_malformed_commits_withhold(self):
        cases = {
            "short sha": (CommitObservation("abc", "a", "a", "m"), ""),
            "upper sha": (CommitObservation("C" * 40, "a", "a", "m"), ""),
            "login not str": (CommitObservation(HEAD, 7, "a", "m"), HEAD),
            "message not str": (CommitObservation(HEAD, "a", "a", None), HEAD),
            "not a commit": ({"sha": HEAD}, ""),
        }
        for label, (bad, ref) in cases.items():
            with self.subTest(label):
                result = derive_material_authors((bad, commit(HEAD)), HEAD)
                self.assertEqual((), result.authors)
                self.assertIn((ref, "INVALID_COMMIT"), result.findings)

    def test_commits_not_a_tuple_withholds(self):
        result = derive_material_authors([commit(HEAD)], HEAD)
        self.assertEqual((), result.authors)
        self.assertIn(("", "INVALID_COMMIT"), result.findings)

    def test_invalid_head_withholds(self):
        result = derive_material_authors((commit(HEAD),), "HEAD")
        self.assertEqual((), result.authors)
        self.assertIn(("", "INVALID_SHA"), result.findings)

    def test_list_at_github_cap_is_treated_as_truncated(self):
        shas = [f"{i:040x}" for i in range(1, COMMIT_LIST_CAP)] + [HEAD]
        result = derive_material_authors(tuple(commit(s) for s in shas), HEAD)
        self.assertWithheld(result, (("", "COMMIT_LIST_TRUNCATED"),))
        below = derive_material_authors(tuple(commit(s) for s in shas[1:]), HEAD)
        self.assertEqual(("NTinkicht", "claude"), below.authors)

    def test_findings_are_deterministic_and_sorted(self):
        commits = (commit(SECOND, author=None), commit(FIRST, message="Material-Author:"))
        first = derive_material_authors(commits, HEAD)
        self.assertEqual(first, derive_material_authors(commits, HEAD))
        self.assertEqual(tuple(sorted(first.findings)), first.findings)
        self.assertEqual((("", "HEAD_NOT_LAST_COMMIT"), (FIRST, "INVALID_MATERIAL_AUTHOR_TRAILER"),
                          (SECOND, "UNATTRIBUTED_COMMIT")), first.findings)


class IndependenceThroughPrInconsistenciesTests(unittest.TestCase):
    snapshot = WorkSnapshot(main_sha=MAIN, observed_main_sha=MAIN, issue_ids=(5,),
                            next_ids=(), pr_issue_bindings=((9, 5),), active_lease_issue_ids=())

    def findings(self, approver, commits):
        authors = derive_material_authors(commits, HEAD).authors
        obs = PullRequestObservation(
            pr=9, issue=5, recorded_head_sha=HEAD, observed_head_sha=HEAD, base_sha=MAIN,
            approved_head_sha=HEAD, approved_base_sha=MAIN, approved_by=approver,
            ci_head_sha=HEAD, ci_base_sha=MAIN, ci_conclusion="success",
            merge_ready_claimed=True, material_authors=authors)
        return pr_inconsistencies(self.snapshot, (obs,), trusted_reviewers=(BOT, "alice"))

    def test_independent_reviewer_is_accepted(self):
        self.assertEqual((), self.findings(BOT, (commit(FIRST, author="alice"), commit(HEAD))))

    def test_co_author_from_an_earlier_commit_cannot_approve(self):
        self.assertEqual(((9, "UNSUPPORTED_MERGE_READY"), (9, "UNTRUSTED_APPROVAL")),
                         self.findings("alice", (commit(FIRST, author="Alice"), commit(HEAD))))

    def test_withheld_authorship_is_never_independence_proof(self):
        self.assertEqual(((9, "UNSUPPORTED_MERGE_READY"), (9, "UNTRUSTED_APPROVAL")),
                         self.findings(BOT, (commit(HEAD, author=None),)))


if __name__ == "__main__":
    unittest.main()
