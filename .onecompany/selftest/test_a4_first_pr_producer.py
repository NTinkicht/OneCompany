from __future__ import annotations

import base64
import copy
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
        }]},
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

    def call(self, method: str, path: str, payload=None):
        if method == "GET" and path == "/":
            return {"default_branch": "main"}
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
        inputs = installation()
        api = FakeGitHub(REPO)
        one = producer.produce(api, **inputs)
        two = producer.produce(api, **inputs)
        self.assertEqual(one, two)
        self.assertEqual(api.created_refs, 1)
        self.assertEqual(api.created_prs, 1)
        self.assertEqual(one["head"], CLAIM)

    def test_two_independent_installations_no_cross_authority(self):
        a = FakeGitHub("owner/disposable-a")
        b = FakeGitHub("another/disposable-b")
        aa = producer.produce(a, **installation("owner/disposable-a", "WU-A"))
        bb = producer.produce(b, **installation("another/disposable-b", "WU-B"))
        self.assertNotEqual(aa["repository"], bb["repository"])
        self.assertNotEqual(aa["branch"], bb["branch"])
        self.assertEqual((a.created_prs, b.created_prs), (1, 1))
        with self.assertRaisesRegex(producer.Refused, "project_identity"):
            producer.produce(b, **installation("owner/disposable-a", "WU-A"))

    def test_forged_or_orphaned_branch_fails_closed(self):
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
        inputs = installation()
        api = FakeGitHub(REPO)
        producer.produce(api, **inputs)
        api.prs[0]["state"] = "closed"
        with self.assertRaisesRegex(producer.Refused, "closed_or_draft"):
            producer.produce(api, **inputs)
        self.assertEqual(api.created_prs, 1)

    def test_duplicate_unmanaged_prs_are_not_self_reconciled(self):
        inputs = installation()
        api = FakeGitHub(REPO)
        producer.produce(api, **inputs)
        api.prs.append(copy.deepcopy(api.prs[0]))
        api.prs[-1]["number"] = 40
        with self.assertRaisesRegex(producer.Refused, "duplicate_canonical_pr"):
            producer.produce(api, **inputs)
        self.assertEqual(api.created_prs, 1)

    def test_base_move_and_unknown_provider_are_refused(self):
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

    def test_pre_pr_binding_and_exact_fixture_only(self):
        inputs = installation()
        inputs["queue"]["work_units"][0]["pr"] = 2
        with self.assertRaisesRegex(producer.Refused, "not_canonically_pre_pr_bound"):
            producer.produce(FakeGitHub(REPO), **inputs)
        inputs["queue"]["work_units"][0]["pr"] = None
        inputs["queue"]["work_units"][0]["write_scope"] = ["**/*"]
        with self.assertRaisesRegex(producer.Refused, "not_exact_fixture_scope"):
            producer.produce(FakeGitHub(REPO), **inputs)

    def test_identities_are_strictly_bound(self):
        for malformed in ("WU/../../X", "WU-$HOME", "WU with space"):
            with self.assertRaises(producer.Refused):
                producer.branch_for(malformed)
        inputs = installation()
        inputs["config"]["autonomy"]["level"] = "L1"
        with self.assertRaisesRegex(producer.Refused, "project_l2_approval_missing"):
            producer.produce(FakeGitHub(REPO), **inputs)


if __name__ == "__main__":
    unittest.main()
