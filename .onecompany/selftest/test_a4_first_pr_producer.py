from __future__ import annotations

import base64
import copy
import os
from contextlib import redirect_stderr
from io import StringIO
from unittest.mock import patch
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import a4_pr_producer as producer

BASE = "a" * 40
CLAIM = "b" * 40
REPO = "owner/disposable-a"
WU = "WU-A"


def installation(repo: str = REPO, wu: str = WU, actor: str = "fixture-bot"):
    """Build synthetic project-scoped capability, policy and queue inputs."""
    branch = producer.branch_for(wu)
    return {
        "repo": repo, "actor": actor, "wu": wu, "checkout_sha": BASE,
        "actions": True, "enabled": True,
        "config": {
            "autonomy": {"level": "L2"},
            "project": {"repository": repo, "default_branch": "main"},
            "safety": {"emergency_stop": False},
        },
        "queue": {"work_units": [{
            "id": wu, "status": "READY", "risk_class": "LOW",
            "branch": branch, "pr": None, "dependencies": [],
            "write_scope": [producer.fixture_path(wu)],
        }]},
        "readiness": {"actors": [{
            "actor_id": actor, "setup_state": "ready",
            "verified_capabilities": ["implementation"],
            "repository_access": {"write": True},
            "unattended": {"verified": True},
            "capacity": {"measured": True, "implementation_streams": 1},
        }]},
        "actors": {"actors": [{
            "id": actor, "enabled": True, "configured": True,
            "capabilities": ["implementation"],
            "cost_class": "FREE_ALLOWANCE",
        }]},
        "budget": {
            "ai": {
                "additional_monthly_spend_cap": 0,
                "allow_paid_fallback": False, "allow_overage": False,
                "allow_auto_topup": False,
                "allow_new_paid_vendor": False,
                "unknown_cost_behavior": "forbid",
            },
            "ci": {"runner_cost_policy": "included_or_free_only"},
            "cost_classes": {
                "allowed": ["FREE_ALLOWANCE", "LOCAL", "INCLUDED_SUBSCRIPTION"],
                "conditionally_allowed": [], "forbidden": ["METERED_ALLOWED", "UNKNOWN_COST"],
            },
        },
        "dispatch": {"actors": [{
            "actor_id": actor, "mechanisms": [{
                "id": "github-actions-a4-pr-producer",
                "kind": "github_action", "configured": True,
                "unattended": True, "capabilities": ["implementation"],
            }],
        }]},
    }


class FakeGitHub:
    """Deliberately shared per-installation model of GitHub's atomic ref API."""

    def __init__(self, repo: str, base: str = BASE):
        """Initialize deterministic shared GitHub ref and PR state."""
        self.repository = repo
        self.base = base
        self.refs = {"main": base}
        self.parents = {}
        self.files = {}
        self.prs = []
        self.created_refs = 0
        self.created_prs = 0
        self.next_blob = "c" * 40
        self.next_tree = "d" * 40
        self.next_commit = CLAIM
        self.lose_pr_response = False
        self.extra_diff = False
        self.visibility = "public"
        self.private = False

    def call(self, method: str, path: str, payload=None):
        """Model GitHub reads, atomic ref creation and PR mutation for race tests."""
        if method == "GET" and path == "/":
            return {"default_branch": "main", "private": self.private, "visibility": self.visibility}
        if method == "GET" and path.startswith("/git/ref/heads/"):
            branch = path.split("/git/ref/heads/", 1)[1]
            if branch not in self.refs:
                raise producer.ApiFailure(404)
            return {"object": {"sha": self.refs[branch]}}
        if method == "GET" and path.startswith("/git/commits/"):
            sha = path.rsplit("/", 1)[1]
            if sha == BASE:
                return {"tree": {"sha": "f" * 40}, "parents": []}
            if sha not in self.parents:
                raise producer.ApiFailure(404)
            return {"parents": [{"sha": self.parents[sha]}]}
        if method == "POST" and path == "/git/blobs":
            self.blob_body = payload["content"]
            return {"sha": self.next_blob}
        if method == "POST" and path == "/git/trees":
            self.fixture_path = payload["tree"][0]["path"]
            return {"sha": self.next_tree}
        if method == "POST" and path == "/git/commits":
            self.parents[self.next_commit] = payload["parents"][0]
            self.files[self.next_commit] = self.blob_body
            return {"sha": self.next_commit}
        if method == "POST" and path == "/git/refs":
            branch = payload["ref"].split("refs/heads/", 1)[1]
            if branch in self.refs:
                raise producer.ApiFailure(422)
            self.refs[branch] = payload["sha"]
            self.created_refs += 1
            return {"ref": payload["ref"]}
        if method == "GET" and path.startswith("/compare/"):
            changed = [{"filename": self.fixture_path, "status": "added"}]
            if self.extra_diff:
                changed.append({"filename": "hidden.py", "status": "added"})
            return {"files": changed}
        if method == "GET" and path.startswith("/contents/"):
            sha = path.split("?ref=", 1)[1]
            if sha not in self.files:
                raise producer.ApiFailure(404)
            return {"type": "file", "encoding": "base64",
                    "content": base64.b64encode(
                        self.files[sha].encode("utf-8")
                    ).decode("ascii")}
        if method == "GET" and path.startswith("/pulls?"):
            return list(self.prs)
        if method == "POST" and path == "/pulls":
            self.created_prs += 1
            branch = payload["head"]
            pr = {
                "number": self.created_prs, "state": "open",
                "draft": False,
                "head": {
                    "sha": self.refs[branch], "ref": branch,
                    "repo": {"full_name": self.repository},
                },
                "base": {
                    "sha": self.base, "ref": "main",
                    "repo": {"full_name": self.repository},
                },
            }
            self.prs.append(pr)
            if self.lose_pr_response:
                self.lose_pr_response = False
                raise producer.ApiFailure(502)
            return pr
        if method == "GET" and path.startswith("/pulls/"):
            number = int(path.rsplit("/", 1)[1])
            return next(pr for pr in self.prs if pr["number"] == number)
        raise AssertionError((method, path))


class FirstPRProducerTests(unittest.TestCase):
    def test_first_start_and_duplicate_delivery_are_one_pr(self):
        """Confirm replay does not open another branch, commit or PR."""
        inputs = installation()
        api = FakeGitHub(REPO)
        one = producer.produce(api, **inputs)
        two = producer.produce(api, **inputs)
        self.assertEqual(one, two)
        self.assertEqual(api.created_refs, 1)
        self.assertEqual(api.created_prs, 1)
        self.assertEqual(one["head"], CLAIM)

    def test_two_independent_installations_no_cross_authority(self):
        """Prove separate project identities and foreign replay refusal."""
        a = FakeGitHub("owner/disposable-a")
        b = FakeGitHub("another/disposable-b")
        aa = producer.produce(a, **installation("owner/disposable-a", "WU-A"))
        bb = producer.produce(b, **installation("another/disposable-b", "WU-B"))
        self.assertNotEqual(aa["repository"], bb["repository"])
        self.assertNotEqual(aa["branch"], bb["branch"])
        self.assertEqual((a.created_prs, b.created_prs), (1, 1))
        with self.assertRaisesRegex(producer.Refused, "project_identity"):
            producer.produce(b, **installation("owner/disposable-a", "WU-A"))

    def test_claim_may_not_smuggle_extra_files(self):
        """Reject a valid fixture commit that also changes unauthorized files."""
        api = FakeGitHub(REPO)
        inputs = installation()
        producer.produce(api, **inputs)
        api.extra_diff = True
        with self.assertRaisesRegex(producer.Refused, "outside_exact_fixture_scope"):
            producer.produce(api, **inputs)

    def test_racing_branch_ref_winner_is_reconciled(self):
        """Recover the canonical winner after an ambiguous create-ref response."""
        class LostCreateResponse(FakeGitHub):
            def call(self, method, path, payload=None):
                """Model GitHub reads, atomic ref creation and PR mutation for race tests."""
                if method == "POST" and path == "/git/refs":
                    super().call(method, path, payload)
                    raise producer.ApiFailure(422)
                return super().call(method, path, payload)
        api = LostCreateResponse(REPO)
        result = producer.produce(api, **installation())
        self.assertEqual(result["pr"], 1)
        self.assertEqual((api.created_refs, api.created_prs), (1, 1))

    def test_forged_or_orphaned_branch_fails_closed(self):
        """Refuse unrelated existing branches instead of hijacking them."""
        inputs = installation()
        api = FakeGitHub(REPO)
        branch = producer.branch_for(WU)
        api.refs[branch] = CLAIM
        api.parents[CLAIM] = "e" * 40
        api.files[CLAIM] = "unrelated branch"
        with self.assertRaisesRegex(producer.Refused, "not_exact_claim"):
            producer.produce(api, **inputs)
        self.assertEqual(api.created_prs, 0)

    def test_previous_success_with_lost_response_is_reconciled(self):
        """Recover existing PR from GitHub after the create response is lost."""
        inputs = installation()
        api = FakeGitHub(REPO)
        api.lose_pr_response = True
        with self.assertRaisesRegex(producer.Refused, "pr_creation_uncertain"):
            producer.produce(api, **inputs)
        self.assertEqual(api.created_prs, 1)
        result = producer.produce(api, **inputs)
        self.assertEqual(result["pr"], 1)
        self.assertEqual(api.created_prs, 1)

    def test_closed_pr_never_reopened_by_duplicate_dispatch(self):
        """Do not replace or reopen a closed canonical PR."""
        inputs = installation()
        api = FakeGitHub(REPO)
        producer.produce(api, **inputs)
        api.prs[0]["state"] = "closed"
        with self.assertRaisesRegex(producer.Refused, "closed_or_draft"):
            producer.produce(api, **inputs)
        self.assertEqual(api.created_prs, 1)

    def test_duplicate_unmanaged_prs_are_not_self_reconciled(self):
        """Refuse multiple matching PR identities instead of guessing a winner."""
        inputs = installation()
        api = FakeGitHub(REPO)
        producer.produce(api, **inputs)
        api.prs.append(copy.deepcopy(api.prs[0]))
        api.prs[-1]["number"] = 40
        with self.assertRaisesRegex(producer.Refused, "duplicate_canonical_pr"):
            producer.produce(api, **inputs)
        self.assertEqual(api.created_prs, 1)

    def test_base_move_and_unknown_provider_are_refused(self):
        """Refuse drifted default branch, stop and unavailable actor capacity."""
        inputs = installation()
        api = FakeGitHub(REPO)
        api.refs["main"] = "9" * 40
        with self.assertRaisesRegex(producer.Refused, "trusted_checkout"):
            producer.produce(api, **inputs)
        api.refs["main"] = BASE
        inputs["config"]["safety"]["emergency_stop"] = True
        with self.assertRaisesRegex(producer.Refused, "emergency_stop"):
            producer.produce(api, **inputs)
        inputs["config"]["safety"]["emergency_stop"] = False
        inputs["readiness"]["actors"][0]["unattended"]["verified"] = False
        with self.assertRaisesRegex(producer.Refused, "unattended_write_unverified"):
            producer.produce(api, **inputs)
        self.assertEqual(api.created_refs, 0)

    def test_foreign_base_or_broad_budget_is_denied(self):
        """Keep base identity and zero-extra-spend policy binding."""
        inputs = installation()
        inputs["budget"]["ai"]["allow_overage"] = True
        with self.assertRaisesRegex(producer.Refused, "zero_extra_spend"):
            producer.produce(FakeGitHub(REPO), **inputs)
        inputs["budget"]["ai"]["allow_overage"] = False
        api = FakeGitHub(REPO)
        producer.produce(api, **inputs)
        api.prs[0]["base"]["ref"] = "unrelated"
        with self.assertRaisesRegex(producer.Refused, "pr_targets_foreign_base"):
            producer.produce(api, **inputs)

    def test_unavailable_actor_refused(self):
        """Reject a temporarily unavailable implementation capability."""
        inputs = installation()
        inputs["readiness"]["actors"][0][
            "temporarily_unavailable_capabilities"
        ] = ["implementation"]
        api = FakeGitHub(REPO)
        with self.assertRaisesRegex(
            producer.Refused, "actor_unattended_write_unverified"
        ):
            producer.produce(api, **inputs)
        self.assertEqual(api.created_refs, 0)

    def test_missing_branch_object_is_refusal_not_uncaught_key_error(self):
        """Represent malformed GitHub ref payload as an explicit refusal."""
        class BrokenRef(FakeGitHub):
            """Drop the base-ref object to exercise malformed HTTP data."""

            def call(self, method, path, payload=None):
                """Return an incomplete branch response for the default ref."""
                if method == "GET" and path == "/git/ref/heads/main":
                    return {"object": {}}
                return super().call(method, path, payload)

        with self.assertRaisesRegex(
            producer.Refused, "trusted_checkout_or_base_moved"
        ):
            producer.produce(BrokenRef(REPO), **installation())

    def test_unknown_cost_and_paid_vendor_fail_before_mutation(self):
        """Reject permissive budgets and individually forbidden actors."""
        for name, value in (
            ("allow_new_paid_vendor", True),
            ("unknown_cost_behavior", "allow_within_cap"),
        ):
            with self.subTest(name=name):
                inputs = installation()
                inputs["budget"]["ai"][name] = value
                api = FakeGitHub(REPO)
                with self.assertRaisesRegex(producer.Refused, "zero_extra_spend"):
                    producer.produce(api, **inputs)
                self.assertEqual(api.created_refs, 0)
        inputs = installation()
        inputs["actors"]["actors"][0]["cost_class"] = "METERED_ALLOWED"
        api = FakeGitHub(REPO)
        with self.assertRaisesRegex(producer.Refused, "actor_cost_class"):
            producer.produce(api, **inputs)
        self.assertEqual(api.created_refs, 0)

    def test_malformed_unavailability_is_refused(self):
        """Fail closed for null or invalid temporary actor capacity states."""
        for value in (None, "implementation", 1, {"implementation": True}):
            with self.subTest(value=value):
                inputs = installation()
                inputs["readiness"]["actors"][0][
                    "temporarily_unavailable_capabilities"
                ] = value
                api = FakeGitHub(REPO)
                with self.assertRaisesRegex(producer.Refused, "actor_unattended_write"):
                    producer.produce(api, **inputs)
                self.assertEqual(api.created_refs, 0)

    def test_malformed_pr_create_response_reconciles_on_next_invocation(self):
        """Do not dereference a successful mutation's malformed JSON reply."""
        class InvalidCreateReply(FakeGitHub):
            """Model a successful PR POST that returns JSON null."""

            def call(self, method, path, payload=None):
                """Replace only the first newly created PR response."""
                if method == "POST" and path == "/pulls":
                    super().call(method, path, payload)
                    return None
                return super().call(method, path, payload)

        api = InvalidCreateReply(REPO)
        with self.assertRaisesRegex(producer.Refused, "pr_creation_uncertain"):
            producer.produce(api, **installation())
        result = producer.produce(api, **installation())
        self.assertEqual(result["pr"], 1)
        self.assertEqual(api.created_prs, 1)

    def test_run_identity_required_before_mutating_github(self):
        """No GitHub API or subprocess write can precede run provenance."""
        with (
            patch.dict(os.environ, {
                "GITHUB_REPOSITORY": REPO, "GH_TOKEN": "synthetic-token",
                "A4_ACTOR": "fixture-bot", "A4_WORK_UNIT": WU,
                "GITHUB_RUN_ID": "", "GITHUB_RUN_ATTEMPT": "",
            }),
            patch.object(producer, "produce") as write,
            patch.object(producer.subprocess, "run") as process,
            redirect_stderr(StringIO()) as stderr,
        ):
            self.assertEqual(producer.main(), 2)
        write.assert_not_called()
        process.assert_not_called()
        self.assertIn("immutable_github_run_identity_missing", stderr.getvalue())

    def test_nonpublic_runner_denied_before_any_write(self):
        """Avoid private Actions charges even when project policy is permissive."""
        inputs = installation()
        for visibility, private in (("private", True), (None, False)):
            with self.subTest(visibility=visibility):
                api = FakeGitHub(REPO)
                api.visibility = visibility
                api.private = private
                with self.assertRaisesRegex(
                    producer.Refused, "public_disposable_runner"
                ):
                    producer.produce(api, **inputs)
                self.assertEqual(api.created_refs, 0)

    def test_pre_pr_binding_and_exact_fixture_only(self):
        """Require an unbound READY WU and precisely one fixture path."""
        inputs = installation()
        inputs["queue"]["work_units"][0]["pr"] = 2
        with self.assertRaisesRegex(producer.Refused, "not_canonically_pre_pr_bound"):
            producer.produce(FakeGitHub(REPO), **inputs)
        inputs["queue"]["work_units"][0]["pr"] = None
        inputs["queue"]["work_units"][0]["write_scope"] = ["**/*"]
        with self.assertRaisesRegex(producer.Refused, "not_exact_fixture_scope"):
            producer.produce(FakeGitHub(REPO), **inputs)

    def test_identities_are_strictly_bound(self):
        """Refuse malformed WU names and source L1 autonomy."""
        for malformed in ("WU/../../X", "WU-$HOME", "WU with space"):
            with self.assertRaises(producer.Refused):
                producer.branch_for(malformed)
        inputs = installation()
        inputs["config"]["autonomy"]["level"] = "L1"
        with self.assertRaisesRegex(producer.Refused, "project_l2_approval_missing"):
            producer.produce(FakeGitHub(REPO), **inputs)


if __name__ == "__main__":
    unittest.main()
