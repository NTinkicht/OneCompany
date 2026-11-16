"""VerifiedWriterReadSide.inspect: one single-defect world per refusal, with a positive control."""
from __future__ import annotations
import base64
import copy
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from github_app import AdapterRefused, AppClient
from settings import Settings
from write_authority import VerifiedWriterReadSide
from write_policy import WriteRefused, WriteRequest

REPO = "NTinkicht/OneCompany"
MAIN = "b" * 40
HEAD = "a" * 40
NOW = dt.datetime(2026, 9, 19, 12, 0, tzinfo=dt.timezone.utc)
CREATED = "2026-09-19T11:00:00Z"
ACTOR = "grok-4-6-interactive"
POLICY_PATHS = {
    "queue": ".onecompany/queue.json", "planning": ".onecompany/planning.json",
    "actors": ".onecompany/actors.json", "readiness": ".onecompany/readiness.json",
    "budget": ".onecompany/budget.json",
}


def settings(repository=REPO):
    return Settings(True, "x" * 42, 5003121, 163077002, Path("/not-present"),
                    repository, "onecompany-github-adapter.onrender.com")


def blob(doc):
    raw = doc if isinstance(doc, bytes) else json.dumps(doc).encode()
    return {"type": "file", "encoding": "base64", "sha": "d" * 40,
            "content": base64.b64encode(raw).decode()}


def world():
    docs = {
        ".onecompany/config.json": {"safety": {"emergency_stop": False},
                                    "autonomy": {"level": "L1"},
                                    "project": {"repository": REPO, "default_branch": "main"}},
        ".onecompany/ledger.json": {"enabled": True, "event_format_version": 2, "issue_number": 21,
                                    "trusted_publisher_logins": ["NTinkicht"],
                                    "lease_lifecycle": {"implicit_expiry_revokes_authority": True,
                                                        "ttl_seconds": 14400}},
        ".onecompany/queue.json": {"work_units": [{"id": "WU-X", "branch": "wu-x", "pr": 106,
                                                   "status": "READY", "write_scope": ["docs/**"]}]},
        ".onecompany/planning.json": {"p": 1},
        ".onecompany/actors.json": {"actors": [{"id": ACTOR, "enabled": True, "configured": True}]},
        ".onecompany/readiness.json": {"actors": [{
            "actor_id": ACTOR, "repository_access": {"write": True},
            "verified_capabilities": ["implementation"], "capacity": {"implementation_streams": 1}}]},
        ".onecompany/budget.json": {"b": 1},
    }
    return {
        "app": {"id": 5003121, "slug": "onecompany-grok-worker"},
        "repo": {"default_branch": "main"},
        "ref": {"object": {"sha": MAIN}},
        "pr": {"number": 106, "state": "open", "merged_at": None,
               "head": {"sha": HEAD, "ref": "wu-x", "repo": {"full_name": REPO}},
               "base": {"sha": MAIN, "ref": "main", "repo": {"full_name": REPO}}},
        "docs": docs,
        "raw": {},
        "pages": None,
        "comments": [],
    }


def lease_comment(w):
    blobs = {name: "d" * 40 for name in POLICY_PATHS}
    event = {"version": 2, "event_id": "evt1", "type": "ROLE_LEASE_ASSIGNED", "actor": ACTOR,
             "timestamp": CREATED, "payload": {
                 "lease_id": "lease1", "work_unit": "WU-X", "pr": 106, "branch": "wu-x",
                 "role": "implementation", "start_head": HEAD,
                 "admission_snapshot": {
                     "schema": "onecompany-lease-admission-v1", "actor": ACTOR,
                     "actor_eligible": True, "dependencies_complete": True,
                     "trusted_ref": MAIN, "policy_blobs": blobs}}}
    text = "<!-- onecompany-ledger-v1 -->\n```json\n" + json.dumps(event) + "\n```"
    return {"id": 1, "user": {"login": "NTinkicht"}, "created_at": CREATED,
            "updated_at": CREATED, "body": text}


class Fake(AppClient):
    def __init__(self, w, repository=REPO):
        super().__init__(settings(repository))
        self.w = w
        self.w["comments"] = self.w["comments"] or [lease_comment(w)]

    def _jwt(self):
        return "dummy-APP-JWT"

    def _call(self, method, path, token, payload=None):
        w = self.w
        if path == "/app":
            return w["app"]
        if path == f"/repos/{self.settings.repository}/installation":
            return {"id": 163077002}
        if path.endswith("/access_tokens"):
            return {"token": "z" * 48, "permissions": {"contents": "read", "pull_requests": "read"},
                    "repository_selection": "selected",
                    "repositories": [{"full_name": self.settings.repository}]}
        if path == f"/repos/{self.settings.repository}":
            return w["repo"]
        if path.endswith("/git/ref/heads/main"):
            return w["ref"]
        if "/pulls/" in path:
            return w["pr"]
        if "/contents/" in path:
            name = path.split("/contents/", 1)[1].split("?ref=")[0]
            if name in w["raw"]:
                return w["raw"][name]
            return blob(w["docs"][name])
        if "/issues/21/comments" in path:
            if w["pages"] is not None:
                return w["pages"]
            return w["comments"]
        raise AssertionError((method, path))


def request():
    return WriteRequest(ACTOR, "WU-X", "lease1", 106, HEAD, "docs/new.md", "hello\n")


class InspectTests(unittest.TestCase):
    def run_inspect(self, mutate=None, *, enabled=True, repository=REPO):
        w = world()
        if mutate:
            mutate(w)
        return VerifiedWriterReadSide(Fake(w, repository)).inspect(request(), NOW, feature_enabled=enabled)

    def refused(self, reason, mutate=None, **kw):
        with self.assertRaises(WriteRefused) as ctx:
            self.run_inspect(mutate, **kw)
        self.assertEqual(str(ctx.exception), reason)

    def test_positive_control_returns_verified_contract(self):
        result = self.run_inspect()
        self.assertEqual(result["main_sha"], MAIN)
        self.assertEqual(result["lease_id"], "lease1")
        self.assertIs(result["authority_from_model_arguments"], False)
        self.assertIn("not a credential grant", result["note"])

    def test_disabled_and_foreign_repository(self):
        self.refused("writer_disabled", enabled=False)
        self.refused("foreign_repository", repository="NTinkicht/Tabibi")

    def test_unexpected_app_principal(self):
        self.refused("unexpected_app_principal", lambda w: w["app"].update(slug="someone-else"))

    def test_default_branch_checks(self):
        self.refused("default_branch_unverified", lambda w: w["repo"].update(default_branch="develop"))
        self.refused("default_branch_sha_unverified", lambda w: w["ref"].update(object={"sha": "short"}))
        self.refused("default_branch_sha_unverified", lambda w: w.update(ref=["x"]))

    def test_live_pr_base_must_equal_main(self):
        self.refused("live_pr_base_stale", lambda w: w["pr"]["base"].update(sha="c" * 40))
        self.refused("live_pr_base_stale", lambda w: w.update(pr=["x"]))

    def test_base_documents_must_be_valid_files(self):
        def raw(value):
            return lambda w: w["raw"].update({".onecompany/config.json": value})
        self.refused("trusted_base_document_unavailable", raw({"type": "dir"}))
        self.refused("trusted_base_document_unavailable", raw(["x"]))
        self.refused("trusted_base_document_unavailable", raw({**blob({}), "encoding": "utf-8"}))
        self.refused("trusted_base_document_invalid", raw({**blob({}), "content": "!!notbase64!!"}))
        self.refused("trusted_base_document_invalid", raw(blob(b"[1, 2]")))
        self.refused("trusted_base_document_invalid", raw(blob(b"{" + b" " * 128_001 + b"}")))
        self.refused("trusted_base_document_invalid", raw(blob(b"\xff\xfe")))

    def test_durable_ledger_policy(self):
        led = ".onecompany/ledger.json"
        self.refused("durable_ledger_not_active", lambda w: w["docs"][led].update(enabled=False))
        self.refused("durable_ledger_not_active", lambda w: w["docs"][led].update(event_format_version=1))
        for key, value in (("issue_number", 0), ("issue_number", "21"),
                           ("trusted_publisher_logins", ["NTinkicht", "other"]),
                           ("trusted_publisher_logins", ["other"]),
                           ("trusted_publisher_logins", "NTinkicht")):
            with self.subTest(key=key, value=value):
                self.refused("ledger_publisher_policy_unverified",
                             lambda w, k=key, v=value: w["docs"][led].update({k: v}))

    def test_lease_lifecycle_must_expire_implicitly(self):
        led = ".onecompany/ledger.json"
        self.refused("lease_lifecycle_unverified", lambda w: w["docs"][led].pop("lease_lifecycle"))
        self.refused("lease_lifecycle_unverified",
                     lambda w: w["docs"][led]["lease_lifecycle"].update(implicit_expiry_revokes_authority=False))

    def test_ledger_pages_fail_closed(self):
        self.refused("ledger_page_invalid", lambda w: w.update(pages={"not": "a list"}))
        full = [{"id": i + 1, "user": {"login": "stranger"}, "created_at": CREATED,
                 "updated_at": CREATED, "body": "x"} for i in range(50)]
        self.refused("ledger_pagination_limit", lambda w: w.update(pages=copy.deepcopy(full)))

    def test_policy_blobs_must_match_the_lease_admission(self):
        def drift(w):
            w["raw"][".onecompany/budget.json"] = {**blob(w["docs"][".onecompany/budget.json"]),
                                                  "sha": "e" * 40}
        self.refused("lease_base_policy_blobs_unverified", drift)

    def test_actor_readiness_is_required(self):
        act, red = ".onecompany/actors.json", ".onecompany/readiness.json"
        self.refused("actor_writer_readiness_unverified", lambda w: w["docs"][act].update(actors=[]))
        self.refused("actor_writer_readiness_unverified",
                     lambda w: w["docs"][act]["actors"][0].update(enabled=False))
        self.refused("actor_writer_readiness_unverified",
                     lambda w: w["docs"][act]["actors"][0].update(configured=False))
        self.refused("actor_writer_readiness_unverified", lambda w: w["docs"][red].update(actors=[]))
        self.refused("actor_writer_readiness_unverified",
                     lambda w: w["docs"][red]["actors"][0]["repository_access"].update(write=False))
        self.refused("actor_writer_readiness_unverified",
                     lambda w: w["docs"][red]["actors"][0].update(verified_capabilities=["review"]))
        self.refused("actor_writer_readiness_unverified",
                     lambda w: w["docs"][red]["actors"][0]["capacity"].update(implementation_streams=0))

    def test_contract_layer_is_still_applied(self):
        self.refused("trusted_work_unit_binding_invalid",
                     lambda w: w["docs"][".onecompany/queue.json"]["work_units"][0].update(status="BLOCKED"))
        self.refused("emergency_stop_or_config_unavailable",
                     lambda w: w["docs"][".onecompany/config.json"]["safety"].update(emergency_stop=True))

    def test_github_errors_stay_sanitised(self):
        class Boom(Fake):
            def _call(self, method, path, token, payload=None):
                if path.endswith("/git/ref/heads/main"):
                    raise AdapterRefused("http_500")
                return super()._call(method, path, token, payload)
        with self.assertRaises(AdapterRefused) as ctx:
            VerifiedWriterReadSide(Boom(world())).inspect(request(), NOW, feature_enabled=True)
        self.assertEqual(str(ctx.exception), "github_default_branch_http_500")


if __name__ == "__main__":
    unittest.main()
