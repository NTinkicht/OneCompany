#!/usr/bin/env python3
"""Fail-closed contract tests for the sandbox-only GitHub App executor."""
import base64
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from sandbox_app_capabilities import (
    CapabilityBlocked, SandboxApp, WRITE_CLASSES, require_sandbox, require_sha,
    run_sandbox_push_pr, isolated_git_env, write_probe_canary,
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
        app = SandboxApp("NTinkicht/qualification-l5-sandbox", "t" * 32)
        with patch.object(app, "api", return_value={
            "data": {"node": {"isResolved": False, "repository": {
                "nameWithOwner": "NTinkicht/Tabibi"}, "pullRequest": {"number": 7}}}
        }):
            with self.assertRaisesRegex(CapabilityBlocked, "OTHER_REPOSITORY"):
                app.resolve_thread("thread-id", 7)

    def test_wrong_pr_graphql_thread_is_rejected(self):
        app = SandboxApp("NTinkicht/qualification-l5-sandbox", "t" * 32)
        with patch.object(app, "api", return_value={
            "data": {"node": {"isResolved": False, "repository": {
                "nameWithOwner": app.repo}, "pullRequest": {"number": 2}}}
        }), patch.object(app, "_repo_api",
                         return_value={"head": {"ref": "l5-probe/valid-probe"}}):
            with self.assertRaisesRegex(CapabilityBlocked, "NOT_ON_PROBE_PR"):
                app.resolve_thread("thread-id", 7)

    def test_merge_rejects_stale_head_before_write(self):
        app = SandboxApp("NTinkicht/qualification-l5-sandbox", "t" * 32)
        with patch.object(app, "_repo_api", return_value={
            "head": {"sha": "b" * 40}
        }) as api:
            with self.assertRaisesRegex(CapabilityBlocked, "STALE_HEAD"):
                app.merge(7, "a" * 40)
            self.assertEqual(api.call_count, 1)
            self.assertEqual(api.call_args.args[0], "GET")


    def test_direct_rest_path_outside_sandbox_is_refused_without_network(self):
        app = SandboxApp("NTinkicht/qualification-l5-sandbox", "t" * 32)
        with patch("sandbox_app_capabilities.urlopen") as network:
            with self.assertRaisesRegex(CapabilityBlocked, "OUTSIDE_SANDBOX"):
                app.api("POST", "/repos/NTinkicht/Tabibi/issues", {"title": "bad"})
            network.assert_not_called()

    def test_node_nested_repository_is_verified(self):
        app = SandboxApp("NTinkicht/qualification-l5-sandbox", "t" * 32)
        with patch.object(app, "api", return_value={
            "data": {"node": {"isResolved": True, "pullRequest": {
                "number": 3, "repository": {"nameWithOwner": app.repo}}}}
        }), patch.object(app, "_repo_api",
                         return_value={"head": {"ref": "l5-probe/valid-probe"}}):
            with self.assertRaisesRegex(CapabilityBlocked, "ALREADY_RESOLVED"):
                app.resolve_thread("thread-id", 3)


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
                return {"head": {"ref": branch}, "draft": True}
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

    def test_duplicate_comment_operation_is_reconciled_without_post(self):
        app = SandboxApp("NTinkicht/qualification-l5-sandbox", "t" * 32)
        uid = "00000000-0000-0000-0000-000000000701"
        marker = "<!-- l5-sandbox-comment:" + uid + " -->"
        operations = []
        def fake_api(method, suffix, payload=None):
            operations.append((method, suffix))
            if suffix == "/pulls/17":
                return {"head": {"ref": "l5-probe/" + uid}}
            if suffix.startswith("/issues/17/comments?"):
                return {"items": [{"id": 81, "body": "Note\n" + marker}]}
            raise AssertionError((method, suffix))
        with patch.object(app, "_repo_api", side_effect=fake_api):
            result = app.comment(17, "Note", uid)
        self.assertTrue(result["reconciled"])
        self.assertEqual(result["comment"]["id"], 81)
        self.assertTrue(all(method == "GET" for method, _ in operations))


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

    def test_sandbox_graphql_unverified_mutation_node_is_refused(self):
        from sandbox_app_capabilities import GRAPH_READY_MUTATION
        app = SandboxApp("NTinkicht/qualification-l5-sandbox", "t" * 32)
        app._scope_verified = True
        with patch("sandbox_app_capabilities.urlopen") as network:
            with self.assertRaisesRegex(CapabilityBlocked, "GRAPHQL_MUTATION_TARGET_UNVERIFIED"):
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
                    "full_name": repo}}, "draft": True}
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
                return {"number": 17, "head": {"ref": branch}, "merged": True}
            raise AssertionError(suffix)
        with patch.object(SandboxApp, "verify_installation", return_value={
            "default_branch": "main"}), patch.object(
                SandboxApp, "_repo_api", autospec=True, side_effect=fake_api
            ), patch("sandbox_app_capabilities.push_canary") as canary:
            result = run_sandbox_push_pr(repo, "t" * 32, probe_id)
            self.assertEqual(result["verified_write_classes"], [])
            self.assertEqual(result["reconciled_write_classes"], ["push", "create_pr"])
            canary.assert_not_called()

    def test_push_probe_never_runs_without_installation(self):
        with patch.object(SandboxApp, "verify_installation",
                          side_effect=CapabilityBlocked("BLOCK_PERMISSION")):
            with patch("sandbox_app_capabilities.push_canary") as canary:
                with self.assertRaises(CapabilityBlocked):
                    run_sandbox_push_pr("NTinkicht/qualification-l5-sandbox", "t" * 32, "00000000-0000-0000-0000-000000000001")
                canary.assert_not_called()


if __name__ == "__main__":
    unittest.main()
