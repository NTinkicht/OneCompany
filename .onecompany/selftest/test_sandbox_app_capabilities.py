#!/usr/bin/env python3
"""Fail-closed contract tests for the sandbox-only GitHub App executor."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from sandbox_app_capabilities import (
    CapabilityBlocked, SandboxApp, WRITE_CLASSES, require_sandbox, require_sha,
    run_sandbox_push_pr,
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
