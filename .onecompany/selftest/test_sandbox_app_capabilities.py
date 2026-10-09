#!/usr/bin/env python3
"""Fail-closed contract tests for the sandbox-only GitHub App executor."""
import base64
import contextlib
import io
import json
import os
import sys
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from sandbox_app_capabilities import (
    CapabilityBlocked, SandboxApp, WRITE_CLASSES, require_sandbox, require_sha,
    run_sandbox_push_pr, isolated_git_env, write_probe_canary, main, shell,
)


class SandboxAppCapabilityTests(unittest.TestCase):
    def test_managed_repositories_cannot_be_targeted(self):
        for repo in ("NTinkicht/OneCompany", "NTinkicht/Tabibi",
                     "NTinkicht/veritas-atlas", "someone/product", "../../other"):
            with self.subTest(repo=repo), self.assertRaises(CapabilityBlocked):
                require_sandbox(repo)

    def test_explicit_sandbox_name_is_required(self):
        self.assertEqual(require_sandbox("NTinkicht/qualification-l5-sandbox"),
                         "NTinkicht/qualification-l5-sandbox")
        with self.assertRaises(CapabilityBlocked):
            require_sandbox("NTinkicht/qualification-l5-sandbox/extra")

    def test_app_token_cannot_silently_fall_back_to_user_token(self):
        with self.assertRaisesRegex(CapabilityBlocked, "APP_TOKEN_MISSING"):
            SandboxApp("NTinkicht/qualification-l5-sandbox", "")
        with self.assertRaisesRegex(CapabilityBlocked, "APP_TOKEN_MISSING"):
            SandboxApp("NTinkicht/qualification-l5-sandbox", "short")

    def test_all_missing_write_classes_stay_unverified(self):
        self.assertEqual(len(WRITE_CLASSES), 9)
        self.assertIn("resolve_thread", WRITE_CLASSES)
        self.assertIn("merge", WRITE_CLASSES)

    def test_exact_sha_validation(self):
        self.assertEqual(require_sha("a" * 40), "a" * 40)
        for value in ("f" * 39, "g" * 40, "", "A" * 40):
            with self.assertRaises(CapabilityBlocked):
                require_sha(value)

    def test_cross_repository_graphql_thread_is_rejected(self):
        from sandbox_app_capabilities import GRAPH_THREAD_FRAGMENT
        app = SandboxApp("NTinkicht/qualification-l5-sandbox", "t" * 32)
        with patch.object(app, "api", return_value={
            "data": {"node": {"isResolved": False, "repository": {
                "nameWithOwner": "NTinkicht/Tabibi"}, "pullRequest": {"number": 7}}}
        }):
            with self.assertRaisesRegex(CapabilityBlocked, "OTHER_REPOSITORY"):
                app._graph_node("thread-id", GRAPH_THREAD_FRAGMENT)

    def test_resolve_thread_blocked_until_replay_safe(self):
        app = SandboxApp("NTinkicht/qualification-l5-sandbox", "t" * 32)
        with patch.object(app, "api") as network:
            with self.assertRaisesRegex(CapabilityBlocked, "RESOLVE_THREAD_NOT_QUALIFIED"):
                app.resolve_thread("thread-id", 7)
            network.assert_not_called()

    def test_merge_is_blocked_until_exact_base_head_review(self):
        app = SandboxApp("NTinkicht/qualification-l5-sandbox", "t" * 32)
        with patch.object(app, "_repo_api") as api:
            with self.assertRaisesRegex(CapabilityBlocked, "MERGE_NOT_QUALIFIED"):
                app.merge(7, "a" * 40)
            api.assert_not_called()

    def test_direct_rest_path_outside_sandbox_is_refused_without_network(self):
        app = SandboxApp("NTinkicht/qualification-l5-sandbox", "t" * 32)
        with patch("sandbox_app_capabilities.urlopen") as network:
            with self.assertRaisesRegex(CapabilityBlocked, "OUTSIDE_SANDBOX"):
                app.api("POST", "/repos/NTinkicht/Tabibi/issues", {"title": "bad"})
            network.assert_not_called()

    def test_node_nested_repository_can_be_read_without_write_authority(self):
        from sandbox_app_capabilities import GRAPH_THREAD_FRAGMENT
        app = SandboxApp("NTinkicht/qualification-l5-sandbox", "t" * 32)
        with patch.object(app, "api", return_value={
            "data": {"node": {"isResolved": True, "pullRequest": {
                "number": 3, "repository": {"nameWithOwner": app.repo}}}}
        }), patch.object(app, "_repo_api",
                         return_value={"head": {"ref": "l5-probe/valid-probe"}}):
            node = app._graph_node("thread-id", GRAPH_THREAD_FRAGMENT)
            self.assertTrue(node["isResolved"])
            self.assertEqual(app._authorized_graph_nodes, {})

    def test_git_subprocess_env_excludes_host_credentials_and_rewrites(self):
        app = SandboxApp("NTinkicht/qualification-l5-sandbox", "t" * 32)
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            with patch.dict(os.environ, {
                "HOME": "/untrusted/home", "GIT_CONFIG_PARAMETERS": "malicious",
                "GIT_CONFIG_COUNT": "99", "GIT_CONFIG_KEY_0": "url.bad.insteadOf",
                "GIT_SSH_COMMAND": "malicious", "GH_TOKEN": "host-token",
                "GITHUB_TOKEN": "host-token", "GIT_ASKPASS": "/host/askpass",
            }):
                env = isolated_git_env(app, home / "askpass", home)
                for key in ("GIT_CONFIG_PARAMETERS", "GIT_SSH_COMMAND",
                            "GH_TOKEN", "GITHUB_TOKEN"):
                    self.assertNotIn(key, env)
                self.assertEqual(env["HOME"], str(home))
                self.assertEqual(env["GIT_CONFIG_NOSYSTEM"], "1")
                self.assertEqual(env["GIT_CONFIG_GLOBAL"], os.devnull)
                self.assertEqual(env["GIT_CONFIG_COUNT"], "2")
                self.assertEqual(env["GIT_CONFIG_KEY_0"], "credential.helper")
                self.assertEqual(env["GIT_CONFIG_VALUE_0"], "")
                self.assertEqual(env["GIT_CONFIG_KEY_1"], "core.hooksPath")
                self.assertEqual(env["GIT_CONFIG_VALUE_1"], os.devnull)
                self.assertEqual(env["GIT_ALLOW_PROTOCOL"], "https")
                self.assertEqual(env["L5_APP_INSTALLATION_TOKEN"], "t" * 32)

    def test_installation_not_proven_fails_before_push(self):
        app = SandboxApp("NTinkicht/qualification-l5-sandbox", "t" * 32)
        with patch.object(app, "api", return_value={"repositories": []}):
            with self.assertRaisesRegex(CapabilityBlocked, "INSTALLATION_NOT_EXCLUSIVE"):
                app.verify_installation()


    def test_probe_identity_required_and_validated_before_write(self):
        app_token = "t" * 32
        with patch.object(SandboxApp, "verify_installation",
                          return_value={"default_branch": "main"}), patch(
                              "sandbox_app_capabilities.push_canary") as canary:
            with self.assertRaisesRegex(CapabilityBlocked, "PROBE_ID_INVALID"):
                run_sandbox_push_pr("NTinkicht/qualification-l5-sandbox",
                                    app_token, "not-a-uuid")
            canary.assert_not_called()

    def test_existing_probe_reconciles_without_second_push_or_pr(self):
        repo = "NTinkicht/qualification-l5-sandbox"
        token = "t" * 32
        probe_id = "00000000-0000-0000-0000-000000000001"
        branch = "l5-probe/" + probe_id
        app = SandboxApp(repo, token)
        def pretend_api(method, suffix, payload=None):
            if suffix.startswith("/branches/"):
                return {"commit": {"sha": "a" * 40}}
            if suffix.startswith("/contents/.l5-sandbox-probes/"):
                return {"content": base64.b64encode(
                    ("Sandbox App qualification probe ID: " + probe_id + "\n").encode()
                ).decode()}
            if suffix.startswith("/pulls?"):
                return {"items": [{"number": 17, "head": {"ref": branch}}]}
            if suffix == "/pulls/17":
                return {"head": {"ref": branch}, "draft": True,
                        "user": {"login": "ntinkicht-l5-sandbox[bot]"}}
            raise AssertionError((method, suffix))
        with patch.object(SandboxApp, "verify_installation",
                          return_value={"default_branch": "main"}), patch.object(
                              SandboxApp, "_repo_api", autospec=True,
                              side_effect=lambda _app, m, path, data=None: pretend_api(m, path, data)
                          ), patch("sandbox_app_capabilities.push_canary") as push, patch.object(
                              SandboxApp, "create_draft_pr") as create:
            result = run_sandbox_push_pr(repo, token, probe_id)
            self.assertEqual(result["sandbox_pr"], 17)
            self.assertEqual(result["verified_write_classes"], [])
            self.assertEqual(result["reconciled_write_classes"], ["push", "create_pr"])
            self.assertEqual(result["status"], "SANDBOX_RECONCILED_PREVIOUS_OPERATION")
            push.assert_not_called()
            create.assert_not_called()


    def test_direct_writes_need_exclusive_installation_preflight(self):
        app = SandboxApp("NTinkicht/qualification-l5-sandbox", "t" * 32)
        with patch("sandbox_app_capabilities.urlopen") as network:
            with self.assertRaisesRegex(CapabilityBlocked, "INSTALLATION_SCOPE_UNVERIFIED"):
                app.api("POST", "/graphql", {"query": "mutation {bad}"})
            with self.assertRaisesRegex(CapabilityBlocked, "INSTALLATION_SCOPE_UNVERIFIED"):
                app.api("POST", "/repos/NTinkicht/qualification-l5-sandbox/issues", {})
            network.assert_not_called()

    def test_installation_with_extra_repository_is_refused(self):
        app = SandboxApp("NTinkicht/qualification-l5-sandbox", "t" * 32)
        with patch.object(app, "api", return_value={"total_count": 2, "repositories": [
            {"full_name": app.repo}, {"full_name": "NTinkicht/Tabibi"},
        ]}):
            with self.assertRaisesRegex(CapabilityBlocked, "INSTALLATION_NOT_EXCLUSIVE"):
                app.verify_installation()
        self.assertFalse(app._scope_verified)

    def test_existing_probe_with_missing_canary_never_qualifies(self):
        repo = "NTinkicht/qualification-l5-sandbox"
        probe_id = "00000000-0000-0000-0000-000000000001"
        def fake_api(_app, method, suffix, payload=None):
            if suffix.startswith("/pulls?"):
                return {"items": [{"number": 17, "head": {
                    "ref": "l5-probe/" + probe_id}}]}
            if suffix.startswith("/branches/"):
                return {"commit": {"sha": "a" * 40}}
            if suffix.startswith("/contents/"):
                return {"content": base64.b64encode(b"NOT THE PROBE").decode()}
            raise AssertionError(suffix)
        with patch.object(SandboxApp, "verify_installation", return_value={
            "default_branch": "main"}), patch.object(
                SandboxApp, "_repo_api", autospec=True, side_effect=fake_api
            ), patch("sandbox_app_capabilities.push_canary") as push:
            with self.assertRaisesRegex(CapabilityBlocked, "PROBE_CANARY_MISMATCH"):
                run_sandbox_push_pr(repo, "t" * 32, probe_id)
            push.assert_not_called()

    def test_comment_requires_durable_cas_before_any_network(self):
        app = SandboxApp("NTinkicht/qualification-l5-sandbox", "t" * 32)
        with patch.object(app, "_repo_api") as api:
            with self.assertRaisesRegex(
                CapabilityBlocked, "COMMENT_REQUIRES_DURABLE_CAS_LEASE"
            ):
                app.comment(17, "Note", "00000000-0000-0000-0000-000000000701")
            api.assert_not_called()

    def test_sandbox_graphql_refuses_organization_scope_mutation(self):
        app = SandboxApp("NTinkicht/qualification-l5-sandbox", "t" * 32)
        app._scope_verified = True
        with patch("sandbox_app_capabilities.urlopen") as network:
            with self.assertRaisesRegex(CapabilityBlocked, "GRAPHQL_OPERATION_FORBIDDEN"):
                app.api("POST", "/graphql", {
                    "query": "mutation { createProjectV2(input:{ownerId:\"org\"}) { projectV2 { id } } }",
                    "variables": {"id": "node"},
                })
            network.assert_not_called()

    def test_sandbox_graphql_mutations_are_unqualified(self):
        from sandbox_app_capabilities import GRAPH_READY_MUTATION
        app = SandboxApp("NTinkicht/qualification-l5-sandbox", "t" * 32)
        app._scope_verified = True
        with patch("sandbox_app_capabilities.urlopen") as network:
            with self.assertRaisesRegex(CapabilityBlocked, "GRAPHQL_OPERATION_FORBIDDEN"):
                app.api("POST", "/graphql", {
                    "query": GRAPH_READY_MUTATION, "variables": {"id": "other-org"}
                })
            network.assert_not_called()

    def test_probe_file_symlink_does_not_overwrite_external_file(self):
        probe_id = "00000000-0000-0000-0000-000000000001"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            probes = root / ".l5-sandbox-probes"
            probes.mkdir()
            victim = root / "victim"
            victim.write_text("original", encoding="utf-8")
            (probes / (probe_id + ".txt")).symlink_to(victim)
            with self.assertRaisesRegex(CapabilityBlocked, "PROBE_FILE_ALREADY_EXISTS"):
                write_probe_canary(probes, probe_id)
            self.assertEqual(victim.read_text(encoding="utf-8"), "original")

    def test_partial_retry_credits_only_new_pr_creation(self):
        repo = "NTinkicht/qualification-l5-sandbox"
        probe_id = "00000000-0000-0000-0000-000000000001"
        branch = "l5-probe/" + probe_id
        def fake_api(_app, method, suffix, payload=None):
            if suffix.startswith("/pulls?"):
                return {"items": []}
            if suffix.startswith("/branches/"):
                return {"commit": {"sha": "a" * 40}}
            if suffix.startswith("/contents/"):
                return {"content": base64.b64encode(
                    ("Sandbox App qualification probe ID: " + probe_id + "\n").encode()
                ).decode()}
            if suffix == "/pulls/17":
                return {"number": 17, "head": {"ref": branch, "repo": {
                    "full_name": repo}}, "draft": True,
                    "user": {"login": "ntinkicht-l5-sandbox[bot]"}}
            raise AssertionError(suffix)
        with patch.object(SandboxApp, "verify_installation", return_value={
            "default_branch": "main"}), patch.object(
                SandboxApp, "_repo_api", autospec=True, side_effect=fake_api
            ), patch.object(SandboxApp, "create_draft_pr",
                            return_value={"number": 17}), patch(
                "sandbox_app_capabilities.push_canary"
            ) as canary:
            result = run_sandbox_push_pr(repo, "t" * 32, probe_id)
            self.assertEqual(result["verified_write_classes"], ["create_pr"])
            self.assertEqual(result["reconciled_write_classes"], ["push"])
            canary.assert_not_called()

    def test_merged_deleted_probe_reconciles_without_new_push(self):
        repo = "NTinkicht/qualification-l5-sandbox"
        probe_id = "00000000-0000-0000-0000-000000000001"
        branch = "l5-probe/" + probe_id
        def fake_api(_app, method, suffix, payload=None):
            if suffix.startswith("/pulls?"):
                return {"items": [{"number": 17, "head": {"ref": branch},
                                   "merged_at": "2026-10-09T02:00:00Z"}]}
            if suffix.startswith("/branches/"):
                raise CapabilityBlocked("REMOTE_REQUEST_FAILED:404")
            if suffix.startswith("/contents/"):
                return {"content": base64.b64encode(
                    ("Sandbox App qualification probe ID: " + probe_id + "\n").encode()
                ).decode()}
            if suffix == "/pulls/17":
                return {"number": 17, "head": {"ref": branch}, "merged": True,
                        "user": {"login": "ntinkicht-l5-sandbox[bot]"}}
            raise AssertionError(suffix)
        with patch.object(SandboxApp, "verify_installation", return_value={
            "default_branch": "main"}), patch.object(
                SandboxApp, "_repo_api", autospec=True, side_effect=fake_api
            ), patch("sandbox_app_capabilities.push_canary") as canary:
            result = run_sandbox_push_pr(repo, "t" * 32, probe_id)
            self.assertEqual(result["verified_write_classes"], [])
            self.assertEqual(result["reconciled_write_classes"], ["push", "create_pr"])
            canary.assert_not_called()


    def test_missing_comment_operation_identity_blocks(self):
        app = SandboxApp("NTinkicht/qualification-l5-sandbox", "t" * 32)
        with patch.object(app, "_repo_api") as api:
            with self.assertRaisesRegex(CapabilityBlocked, "COMMENT_OPERATION_ID_INVALID"):
                app.comment(17, "Note", "malformed")
            api.assert_not_called()


    def test_expected_app_id_is_mandatory(self):
        repo = "NTinkicht/qualification-l5-sandbox"
        app = SandboxApp(repo, "ghs_5245673_not-a-real-token")
        def api(method, path, payload=None):
            if path.startswith("/installation/repositories"):
                return {"total_count": 1, "repositories": [{"full_name": repo}]}
            return {"full_name": repo, "private": True}
        with patch.object(app, "api", side_effect=api), patch.dict(
                os.environ, {}, clear=True):
            with self.assertRaisesRegex(CapabilityBlocked, "EXPECTED_APP_ID_MISSING"):
                app.verify_installation()

    def test_wrong_github_app_token_is_never_qualified(self):
        repo = "NTinkicht/qualification-l5-sandbox"
        app = SandboxApp(repo, "ghs_1234567_different-app-token")
        def api(method, path, payload=None):
            if path.startswith("/installation/repositories"):
                return {"total_count": 1, "repositories": [{"full_name": repo}]}
            return {"full_name": repo, "private": True}
        with patch.object(app, "api", side_effect=api), patch.dict(
                os.environ, {"L5_EXPECTED_APP_ID": "5245673",
                             "L5_ATTESTED_APP_SLUG": "wrong-app"}):
            with self.assertRaisesRegex(CapabilityBlocked, "APP_SLUG_ATTESTATION_FAILED"):
                app.verify_installation()
        self.assertFalse(app._scope_verified)

    def test_forged_attested_slug_cannot_override_other_app_token(self):
        repo = "NTinkicht/qualification-l5-sandbox"
        app = SandboxApp(repo, "ghs_1234567_other-app-token")
        def api(method, path, payload=None):
            if path.startswith("/installation/repositories"):
                return {"total_count": 1, "repositories": [{"full_name": repo}]}
            return {"full_name": repo, "private": True}
        with patch.object(app, "api", side_effect=api), patch.dict(
                os.environ, {"L5_EXPECTED_APP_ID": "5245673",
                             "L5_ATTESTED_APP_SLUG": "ntinkicht-l5-sandbox"}):
            with self.assertRaisesRegex(CapabilityBlocked, "APP_ID_NOT_ATTESTED"):
                app.verify_installation()
        self.assertFalse(app._scope_verified)

    def test_wrong_expected_app_id_does_not_mutate(self):
        repo = "NTinkicht/qualification-l5-sandbox"
        app = SandboxApp(repo, "ghs_1234567_other-app-token")
        def api(method, path, payload=None):
            if path.startswith("/installation/repositories"):
                return {"total_count": 1, "repositories": [{"full_name": repo}]}
            return {"full_name": repo, "private": True}
        with patch.object(app, "api", side_effect=api), patch.dict(
                os.environ, {"L5_EXPECTED_APP_ID": "1234567",
                             "L5_ATTESTED_APP_SLUG": "ntinkicht-l5-sandbox"}):
            with self.assertRaisesRegex(CapabilityBlocked, "EXPECTED_APP_ID_MISMATCH"):
                app.verify_installation()
        self.assertFalse(app._scope_verified)

    def test_expected_github_app_token_can_qualify_preflight(self):
        repo = "NTinkicht/qualification-l5-sandbox"
        app = SandboxApp(repo, "ghs_5245673_matching-token")
        def api(method, path, payload=None):
            if path.startswith("/installation/repositories"):
                return {"total_count": 1, "repositories": [{"full_name": repo}]}
            return {"full_name": repo, "private": True, "default_branch": "main"}
        with patch.object(app, "api", side_effect=api), patch.dict(
                os.environ, {"L5_EXPECTED_APP_ID": "5245673",
                             "L5_ATTESTED_APP_SLUG": "ntinkicht-l5-sandbox"}):
            self.assertEqual(app.verify_installation()["full_name"], repo)
        self.assertTrue(app._scope_verified)

    def test_wrong_pr_bot_cannot_claim_sandbox_write_proof(self):
        repo = "NTinkicht/qualification-l5-sandbox"
        probe_id = "00000000-0000-0000-0000-000000000001"
        branch = "l5-probe/" + probe_id
        def fake_api(_app, method, suffix, payload=None):
            if suffix.startswith("/pulls?"):
                return {"items": [{"number": 17, "head": {"ref": branch}}]}
            if suffix.startswith("/branches/"):
                return {"commit": {"sha": "a" * 40}}
            if suffix.startswith("/contents/"):
                return {"content": base64.b64encode(
                    ("Sandbox App qualification probe ID: " + probe_id + "\n").encode()
                ).decode()}
            if suffix == "/pulls/17":
                return {"head": {"ref": branch}, "user": {"login": "wrong-app[bot]"}}
            raise AssertionError(suffix)
        with patch.object(SandboxApp, "verify_installation",
                          return_value={"default_branch": "main"}), patch.object(
                              SandboxApp, "_repo_api", autospec=True, side_effect=fake_api
                          ), patch("sandbox_app_capabilities.push_canary") as push:
            with self.assertRaisesRegex(CapabilityBlocked, "PR_APP_IDENTITY_MISMATCH"):
                run_sandbox_push_pr(repo, "t" * 32, probe_id)
            push.assert_not_called()



    def test_rate_limit_403_waits_not_permission_denied(self):
        app = SandboxApp("NTinkicht/qualification-l5-sandbox", "t" * 32)
        cases = [{"Retry-After": "10"}, {"x-ratelimit-remaining": "0"}]
        for headers in cases:
            with self.subTest(headers=headers), patch(
                "sandbox_app_capabilities.urlopen",
                side_effect=HTTPError("https://api.github.com", 403,
                                      "Forbidden", headers, None),
            ):
                with self.assertRaisesRegex(CapabilityBlocked, "WAIT_RATE_LIMIT"):
                    app.api("GET", "/repos/NTinkicht/qualification-l5-sandbox")

    def test_github_5xx_errors_are_retryable(self):
        app = SandboxApp("NTinkicht/qualification-l5-sandbox", "t" * 32)
        for code in (500, 502, 503, 504, 599):
            with self.subTest(code=code), patch(
                "sandbox_app_capabilities.urlopen",
                side_effect=HTTPError("https://api.github.com", code,
                                      "Server error", {}, None),
            ):
                with self.assertRaisesRegex(CapabilityBlocked, "WAIT_EXTERNAL:GITHUB_SERVER_ERROR"):
                    app.api("GET", "/repos/NTinkicht/qualification-l5-sandbox")

    def test_github_404_remains_not_found_for_probe_reconciliation(self):
        app = SandboxApp("NTinkicht/qualification-l5-sandbox", "t" * 32)
        with patch("sandbox_app_capabilities.urlopen",
                   side_effect=HTTPError("https://api.github.com", 404,
                                         "Not found", {}, None)):
            with self.assertRaisesRegex(CapabilityBlocked, "REMOTE_REQUEST_FAILED:404"):
                app.api("GET", "/repos/NTinkicht/qualification-l5-sandbox")

    def test_malformed_successful_api_bodies_return_structured_wait(self):
        app = SandboxApp("NTinkicht/qualification-l5-sandbox", "t" * 32)
        for payload in (b"{truncated", b'"scalar"', b'\xff'):
            with self.subTest(payload=payload):
                response = type("Response", (), {
                    "status": 200,
                    "read": lambda self, p=payload: p,
                })()
                with patch("sandbox_app_capabilities.urlopen",
                           return_value=contextlib.nullcontext(response)):
                    with self.assertRaisesRegex(CapabilityBlocked, "WAIT_EXTERNAL"):
                        app.api("GET", "/repos/NTinkicht/qualification-l5-sandbox")

    def test_git_transient_errors_do_not_become_permission_blocks(self):
        failures = [
            "fatal: unable to access repository: Could not resolve host: github.com",
            "fatal: unable to access repository: Connection reset by peer",
            "fatal: unable to access repository: The requested URL returned error: 503",
        ]
        for stderr in failures:
            with self.subTest(stderr=stderr), patch(
                "sandbox_app_capabilities.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    ["git", "push"], 128, stdout="", stderr=stderr,
                ),
            ):
                with self.assertRaisesRegex(CapabilityBlocked, "WAIT_EXTERNAL:GIT_TRANSPORT_FAILURE"):
                    shell(["git", "push"], env={})

    def test_git_auth_failure_is_not_misclassified_as_transient(self):
        with patch("sandbox_app_capabilities.subprocess.run",
                   return_value=subprocess.CompletedProcess(
                       ["git", "push"], 128, stdout="",
                       stderr="fatal: Authentication failed",
                   )):
            with self.assertRaisesRegex(CapabilityBlocked, "LOCAL_COMMAND_FAILED:git"):
                shell(["git", "push"], env={})

    def test_git_timeout_is_retryable(self):
        with patch("sandbox_app_capabilities.subprocess.run",
                   side_effect=subprocess.TimeoutExpired(["git", "push"], 120)):
            with self.assertRaisesRegex(CapabilityBlocked, "WAIT_EXTERNAL:GIT_TRANSPORT_TIMEOUT"):
                shell(["git", "push"], env={})

    def test_actual_forbidden_403_is_permission_block(self):
        app = SandboxApp("NTinkicht/qualification-l5-sandbox", "t" * 32)
        with patch("sandbox_app_capabilities.urlopen",
                   side_effect=HTTPError("https://api.github.com", 403,
                                         "Forbidden", {}, None)):
            with self.assertRaisesRegex(CapabilityBlocked, "APP_REQUEST_REFUSED"):
                app.api("GET", "/repos/NTinkicht/qualification-l5-sandbox")

    def test_cli_preserves_wait_classification(self):
        argv = ["sandbox_app_capabilities.py", "--sandbox-repo",
                "NTinkicht/qualification-l5-sandbox"]
        for reason, expected in (
            ("WAIT_RATE_LIMIT", "WAIT_RATE_LIMIT"),
            ("WAIT_EXTERNAL:NETWORK_UNAVAILABLE", "WAIT_EXTERNAL"),
        ):
            with self.subTest(reason=reason), patch.object(
                    SandboxApp, "verify_installation",
                    side_effect=CapabilityBlocked(reason)), patch.object(
                        sys, "argv", argv), patch.dict(
                            os.environ, {"L5_APP_INSTALLATION_TOKEN": "t" * 32}):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = main()
                self.assertEqual(code, 2)
                payload = json.loads(output.getvalue())
                self.assertEqual(payload["status"], expected)
                self.assertEqual(payload["reason"], reason)


    def test_rejected_graphql_thread_cannot_grant_mutation(self):
        from sandbox_app_capabilities import GRAPH_RESOLVE_MUTATION
        app = SandboxApp("NTinkicht/qualification-l5-sandbox", "t" * 32)
        app._scope_verified = True
        with patch("sandbox_app_capabilities.urlopen") as network:
            with self.assertRaisesRegex(CapabilityBlocked, "RESOLVE_THREAD_NOT_QUALIFIED"):
                app.resolve_thread("thread-id", 18)
            self.assertFalse(app._authorized_graph_nodes)
            with self.assertRaisesRegex(CapabilityBlocked, "GRAPHQL_OPERATION_FORBIDDEN"):
                app.api("POST", "/graphql", {
                    "query": GRAPH_RESOLVE_MUTATION, "variables": {"id": "thread-id"}
                })
            network.assert_not_called()

    def test_failed_graphql_network_mutation_clears_authorization(self):
        from sandbox_app_capabilities import GRAPH_RESOLVE_MUTATION
        app = SandboxApp("NTinkicht/qualification-l5-sandbox", "t" * 32)
        app._authorized_graph_nodes["thread-id"] = "resolve"
        with patch.object(app, "api",
                          side_effect=CapabilityBlocked("WAIT_EXTERNAL:NETWORK_UNAVAILABLE")):
            with self.assertRaisesRegex(CapabilityBlocked, "WAIT_EXTERNAL"):
                app._mutate_graph(GRAPH_RESOLVE_MUTATION, "thread-id", "resolveReviewThread")
        self.assertEqual(app._authorized_graph_nodes, {})

    def test_headerless_secondary_403_still_reports_wait(self):
        app = SandboxApp("NTinkicht/qualification-l5-sandbox", "t" * 32)
        message = b'{"message":"You have exceeded a secondary rate limit. Please wait."}'
        with patch("sandbox_app_capabilities.urlopen",
                   side_effect=HTTPError("https://api.github.com", 403,
                                         "Forbidden", {}, io.BytesIO(message))):
            with self.assertRaisesRegex(CapabilityBlocked, "WAIT_RATE_LIMIT"):
                app.api("GET", "/repos/NTinkicht/qualification-l5-sandbox")

    def test_direct_rest_unqualified_writes_are_refused_without_network(self):
        app = SandboxApp("NTinkicht/qualification-l5-sandbox", "t" * 32)
        app._scope_verified = True
        blocked = [
            ("POST", "/repos/NTinkicht/qualification-l5-sandbox/issues/1/comments"),
            ("POST", "/repos/NTinkicht/qualification-l5-sandbox/actions/jobs/2/rerun"),
            ("POST", "/repos/NTinkicht/qualification-l5-sandbox/pulls/1/requested_reviewers"),
            ("PUT", "/repos/NTinkicht/qualification-l5-sandbox/pulls/1/merge"),
            ("PUT", "/repos/NTinkicht/qualification-l5-sandbox/pulls/1/update-branch"),
        ]
        with patch("sandbox_app_capabilities.urlopen") as network:
            for method, path in blocked:
                with self.subTest(method=method, path=path):
                    with self.assertRaisesRegex(CapabilityBlocked, "REST_WRITE_NOT_QUALIFIED"):
                        app.api(method, path, {})
            network.assert_not_called()

    def test_forged_probe_pr_payload_is_refused(self):
        app = SandboxApp("NTinkicht/qualification-l5-sandbox", "t" * 32)
        app._scope_verified = True
        app._default_branch = "main"
        path = "/repos/NTinkicht/qualification-l5-sandbox/pulls"
        with patch("sandbox_app_capabilities.urlopen") as network:
            for payload in [
                {"head": "main", "base": "main", "draft": True},
                {"head": "l5-probe/not-a-uuid", "base": "main", "draft": True},
                {"head": "l5-probe/00000000-0000-0000-0000-000000000001",
                 "base": "production", "draft": True},
                {"head": "l5-probe/00000000-0000-0000-0000-000000000001",
                 "base": "main", "draft": False},
            ]:
                with self.subTest(payload=payload):
                    with self.assertRaisesRegex(CapabilityBlocked, "PROBE_PR_POST_NOT_QUALIFIED"):
                        app.api("POST", path, payload)
            network.assert_not_called()

    def test_other_unqualified_operations_have_no_network(self):
        app = SandboxApp("NTinkicht/qualification-l5-sandbox", "t" * 32)
        with patch.object(app, "_repo_api") as api:
            for method, args in [
                (app.request_review, (7, "reviewer")),
                (app.update_branch, (7, "a" * 40)),
                (app.mark_ready, ("prnode",)),
            ]:
                with self.subTest(method=method.__name__):
                    with self.assertRaisesRegex(CapabilityBlocked, "NOT_QUALIFIED"):
                        method(*args)
            api.assert_not_called()

    def test_unqualified_rerun_never_dispatches(self):
        app = SandboxApp("NTinkicht/qualification-l5-sandbox", "t" * 32)
        with patch.object(app, "_repo_api") as api:
            with self.assertRaisesRegex(CapabilityBlocked, "RERUN_JOB_NOT_QUALIFIED"):
                app.rerun_job(123)
            api.assert_not_called()

    def test_push_probe_never_runs_without_installation(self):
        with patch.object(SandboxApp, "verify_installation",
                          side_effect=CapabilityBlocked("BLOCK_PERMISSION")):
            with patch("sandbox_app_capabilities.push_canary") as canary:
                with self.assertRaises(CapabilityBlocked):
                    run_sandbox_push_pr("NTinkicht/qualification-l5-sandbox", "t" * 32, "00000000-0000-0000-0000-000000000001")
                canary.assert_not_called()


if __name__ == "__main__":
    unittest.main()
