"""OC-P0-06 / OC-P0-04 (#334): post-merge ledger recovery (``--reconcile-merged``).

``merge._reconcile_merged_pr`` is the only path that records durable
completion for a PR that GitHub already merged when the ledger publication
failed mid-merge. These vectors call the real function with its live readers
and the ledger writer patched, and pin that it never writes a completion for a
PR GitHub did not merge, for an unprotected base, an unmapped Work Unit or an
unauthorized principal, and that replay is idempotent.
"""
from __future__ import annotations

import copy
import io
import sys
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import merge

REPO = "NTinkicht/OneCompany"
PR = 7
WU = "WU900"
HEAD = "a" * 40
BASE = "b" * 40
MERGE_SHA = "c" * 40
ACTOR = "merge-executor"
LOGIN = "merge-executor[bot]"


def pr_doc(**overrides) -> dict:
    value = {
        "number": PR,
        "merged_at": "2026-10-24T12:00:00Z",
        "merge_commit_sha": MERGE_SHA,
        "head": {"sha": HEAD, "ref": "ai/900-example"},
        "base": {"sha": BASE, "ref": "main"},
    }
    value.update(overrides)
    return value


def queue() -> dict:
    return {"work_units": [{"id": WU, "pr": PR}, {"id": "WU901", "pr": PR + 1}]}


def identity() -> dict:
    return {
        "actor_id": ACTOR,
        "login": LOGIN,
        "policy_provenance": {"base_sha": BASE},
    }


def pr_view() -> dict:
    return {
        "active_leases": [
            {"id": "L-impl", "role": "implementation", "actor": "implementer", "pr": PR},
            {"id": "L-review", "role": "review", "actor": "reviewer", "pr": PR},
        ]
    }


class ReconcileMergedTests(unittest.TestCase):
    def run_reconcile(
        self,
        *,
        actor_assertion: str | None = None,
        ledger: bool = True,
        github_result=None,
        protected_result=None,
        queue_result=None,
        identity_result=None,
        already_verified: bool = False,
        verified_after: bool = True,
        publish_error: Exception | None = None,
    ) -> tuple[int, str]:
        github_result = (pr_doc(), None) if github_result is None else github_result
        protected_result = (
            ({"branch": "main"}, []) if protected_result is None else protected_result
        )
        queue_result = (queue(), None) if queue_result is None else queue_result
        identity_result = (identity(), []) if identity_result is None else identity_result
        self.events: list[tuple[str, str, dict]] = []
        global_calls = {"count": 0}

        def view(pr=None):
            if pr is not None:
                self.assertEqual(pr, PR, "lease release must read the reconciled PR only")
                return copy.deepcopy(pr_view())
            global_calls["count"] += 1
            if global_calls["count"] == 1:
                merged = [WU] if already_verified else []
            else:
                merged = [WU] if verified_after else []
            return {"verified_merged_work_units": merged}

        def append(event_type, actor, payload):
            if publish_error is not None and event_type == "MERGED":
                raise publish_error
            self.events.append((event_type, actor, copy.deepcopy(payload)))

        with ExitStack() as stack:
            stack.enter_context(patch.object(merge, "ledger_enabled", return_value=ledger))
            self.github = stack.enter_context(
                patch.object(merge, "_github_pr", return_value=github_result)
            )
            self.protected = stack.enter_context(
                patch.object(
                    merge,
                    "protected_default_branch_context",
                    return_value=protected_result,
                )
            )
            self.base_document = stack.enter_context(
                patch.object(merge, "_base_document", return_value=queue_result)
            )
            self.authorize = stack.enter_context(
                patch.object(
                    merge, "authorize_current_principal", return_value=identity_result
                )
            )
            stack.enter_context(patch.object(merge, "coordination_view", side_effect=view))
            stack.enter_context(
                patch.object(merge, "append_coordination_event", side_effect=append)
            )
            out = io.StringIO()
            with redirect_stdout(out):
                code = merge._reconcile_merged_pr(REPO, PR, actor_assertion)
        return code, out.getvalue()

    def assert_refused(self, result: tuple[int, str], fragment: str) -> None:
        code, output = result
        self.assertEqual(code, 2, output)
        self.assertIn("REFUSED", output)
        self.assertIn(fragment, output)
        self.assertNotIn("MERGE RECONCILED", output)
        self.assertEqual(self.events, [], "a refusal must not write any ledger event")

    # ------------------------------------------------------------------ success

    def test_recovers_completion_with_exact_revisions(self) -> None:
        code, output = self.run_reconcile()
        self.assertEqual(code, 0, output)
        self.assertIn(f"MERGE RECONCILED: PR #{PR} -> {WU} ({MERGE_SHA})", output)
        types = [event[0] for event in self.events]
        self.assertEqual(types, ["ROLE_LEASE_RELEASED", "MERGED"])
        released = self.events[0][2]
        self.assertEqual(released["lease_id"], "L-impl", "only implementation leases are released")
        self.assertEqual(released["reason"], "merged_reconcile")
        event_type, actor, merged = self.events[1]
        self.assertEqual(actor, ACTOR)
        self.assertEqual(merged["pr"], PR)
        self.assertEqual(merged["work_unit"], WU)
        self.assertEqual(merged["approved_head"], HEAD)
        self.assertEqual(merged["approved_base"], BASE)
        self.assertEqual(merged["merge_sha"], MERGE_SHA)
        self.assertEqual(merged["method"], "reconciled")
        self.assertEqual(merged["platform_login"], LOGIN)
        self.assertIs(merged["recovered_after_partial_failure"], True)
        self.protected.assert_called_once_with(REPO, BASE, claimed_branch="main")
        self.base_document.assert_called_once_with(REPO, merge.BASE_QUEUE_PATH, BASE)
        self.authorize.assert_called_once_with(REPO, BASE, "merge_execution")

    def test_actor_assertion_may_name_actor_id_or_login(self) -> None:
        for assertion in (ACTOR, LOGIN):
            with self.subTest(assertion=assertion):
                code, output = self.run_reconcile(actor_assertion=assertion)
                self.assertEqual(code, 0, output)

    def test_replay_after_verified_completion_is_idempotent(self) -> None:
        code, output = self.run_reconcile(already_verified=True)
        self.assertEqual(code, 0, output)
        self.assertIn("already has verified durable completion", output)
        self.assertEqual(self.events, [], "replay must not append a duplicate MERGED event")

    # --------------------------------------------------- refusals before writes

    def test_ledger_disabled_refuses(self) -> None:
        self.assert_refused(self.run_reconcile(ledger=False), "durable ledger is disabled")
        self.github.assert_not_called()

    def test_github_read_failure_refuses(self) -> None:
        self.assert_refused(
            self.run_reconcile(github_result=(None, "HTTP 404")), "HTTP 404"
        )

    def test_unmerged_pr_refuses(self) -> None:
        for merged_at in (None, ""):
            with self.subTest(merged_at=merged_at):
                self.assert_refused(
                    self.run_reconcile(github_result=(pr_doc(merged_at=merged_at), None)),
                    "is not merged",
                )
                self.protected.assert_not_called()
                self.authorize.assert_not_called()

    def test_missing_exact_revisions_refuse(self) -> None:
        vectors = {
            "no head sha": pr_doc(head={"ref": "x"}),
            "head not object": pr_doc(head="a" * 40),
            "empty base sha": pr_doc(base={"sha": "", "ref": "main"}),
            "base not object": pr_doc(base=None),
            "no merge sha": pr_doc(merge_commit_sha=None),
            "merge sha not string": pr_doc(merge_commit_sha=123),
        }
        for name, document in vectors.items():
            with self.subTest(name):
                self.assert_refused(
                    self.run_reconcile(github_result=(document, None)),
                    "lacks exact head/base/merge SHA metadata",
                )
                self.protected.assert_not_called()

    def test_unprotected_base_refuses(self) -> None:
        self.assert_refused(
            self.run_reconcile(
                protected_result=(None, ["base is not the protected default branch"])
            ),
            "base is not the protected default branch",
        )
        self.authorize.assert_not_called()

    def test_unreadable_base_queue_refuses(self) -> None:
        self.assert_refused(
            self.run_reconcile(queue_result=(None, "cannot load base-trusted queue")),
            "cannot load base-trusted queue",
        )

    def test_unmapped_pr_refuses(self) -> None:
        self.assert_refused(
            self.run_reconcile(
                queue_result=({"work_units": [{"id": "WU901", "pr": PR + 1}]}, None)
            ),
            "is not mapped in its base-trusted queue",
        )
        self.authorize.assert_not_called()

    def test_unauthorized_principal_refuses(self) -> None:
        self.assert_refused(
            self.run_reconcile(identity_result=(None, ["missing merge_execution"])),
            "missing merge_execution",
        )

    def test_mismatched_actor_assertion_refuses(self) -> None:
        self.assert_refused(
            self.run_reconcile(actor_assertion="someone-else"),
            "--actor assertion does not match",
        )

    # ------------------------------------------------ refusals after attempted writes

    def test_publication_failure_is_never_success(self) -> None:
        code, output = self.run_reconcile(publish_error=RuntimeError("ledger offline"))
        self.assertEqual(code, 2, output)
        self.assertIn("merge reconciliation publication failed: ledger offline", output)
        self.assertNotIn("MERGE RECONCILED", output)
        self.assertNotIn("MERGED", [event[0] for event in self.events])

    def test_unverified_completion_is_never_success(self) -> None:
        code, output = self.run_reconcile(verified_after=False)
        self.assertEqual(code, 2, output)
        self.assertIn("did not become verified durable completion", output)
        self.assertNotIn("MERGE RECONCILED", output)


if __name__ == "__main__":
    unittest.main()
