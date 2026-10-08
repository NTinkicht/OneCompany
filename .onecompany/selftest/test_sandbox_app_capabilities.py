#!/usr/bin/env python3
"""Fail-closed contract tests for the sandbox-only GitHub App executor."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from sandbox_app_capabilities import (
    CapabilityBlocked, SandboxApp, WRITE_CLASSES, require_sandbox, require_sha,
    run_sandbox_push_pr, isolated_git_env,
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
        }):
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
        }):
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
            with self.assertRaisesRegex(CapabilityBlocked, "SANDBOX_OUTSIDE_INSTALLATION"):
                app.verify_installation()

    def test_push_probe_never_runs_without_installation(self):
        with patch.object(SandboxApp, "verify_installation",
                          side_effect=CapabilityBlocked("BLOCK_PERMISSION")):
            with patch("sandbox_app_capabilities.push_canary") as canary:
                with self.assertRaises(CapabilityBlocked):
                    run_sandbox_push_pr("NTinkicht/qualification-l5-sandbox", "t" * 32)
                canary.assert_not_called()


if __name__ == "__main__":
    unittest.main()
