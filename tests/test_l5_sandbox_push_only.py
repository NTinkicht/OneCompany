"""Adversarial offline coverage for L5 sandbox App push-only qualification.

Discovered by L5 Hostile Controller Candidate CI (test_l5_*.py).
No credentials, network calls, or sandbox mutations are performed.
"""
from __future__ import annotations

import base64
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from sandbox_app_capabilities import (
    CapabilityBlocked, SandboxApp, WRITE_CLASSES, main, run_sandbox_push_pr,
)

REPO = "NTinkicht/qualification-l5-sandbox"
PROBE = "00000000-0000-0000-0000-000000000607"
BRANCH = "l5-probe/" + PROBE
SHA = "a" * 40


class SandboxPushOnlyContractTests(unittest.TestCase):
    def _api(self, app, method, suffix, payload=None):
        if suffix.startswith("/pulls?"):
            return {"items": []}
        if suffix.startswith("/branches/"):
            raise CapabilityBlocked("REMOTE_REQUEST_FAILED:404")
        if suffix == "/contents/.l5-sandbox-probes/" + PROBE + ".txt?ref=main":
            raise CapabilityBlocked("REMOTE_REQUEST_FAILED:404")
        if suffix.startswith("/contents/.l5-sandbox-probes/") and "?ref=" in suffix:
            return {"content": base64.b64encode(
                ("Sandbox App qualification probe ID: " + PROBE + "\n").encode()
            ).decode()}
        raise AssertionError("unexpected sandbox API path: " + suffix)

    def _push(self, app, probe_id):
        self.assertEqual(probe_id, PROBE)
        app._pr_push_authorizations[BRANCH] = SHA
        return BRANCH, "main"

    def test_push_only_proves_one_class_without_pr_creation(self):
        with patch.object(
            SandboxApp, "verify_installation",
            return_value={"default_branch": "main"},
        ), patch.object(
            SandboxApp, "_repo_api", autospec=True, side_effect=self._api
        ), patch.object(
            SandboxApp, "_inspect_exclusive_probe_ruleset"
        ) as policy, patch(
            "sandbox_app_capabilities.push_canary", side_effect=self._push
        ) as pushed, patch.object(SandboxApp, "create_draft_pr") as forbidden:
            out = run_sandbox_push_pr(REPO, "t" * 32, PROBE, push_only=True)
            self.assertEqual(out["status"], "SANDBOX_PUSH_ONLY_PROOF")
            self.assertEqual(out["sandbox_branch"], BRANCH)
            self.assertEqual(out["verified_head_sha"], SHA)
            self.assertEqual(out["verified_write_classes"], ["push"])
            self.assertEqual(out["unverified_write_classes"],
                             list(WRITE_CLASSES[1:]))
            self.assertFalse(out["production_enabled"])
            policy.assert_called_once_with(BRANCH)
            pushed.assert_called_once()
            forbidden.assert_not_called()

    def test_unattested_policy_never_pushes(self):
        with patch.object(
            SandboxApp, "verify_installation",
            return_value={"default_branch": "main"},
        ), patch.object(
            SandboxApp, "_repo_api", autospec=True, side_effect=self._api
        ), patch.object(
            SandboxApp, "_inspect_exclusive_probe_ruleset",
            side_effect=CapabilityBlocked(
                "BLOCK_PERMISSION:PROBE_REF_EXCLUSIVITY_UNVERIFIED"
            ),
        ), patch(
            "sandbox_app_capabilities.push_canary"
        ) as pushed, patch.object(SandboxApp, "create_draft_pr") as forbidden:
            with self.assertRaisesRegex(
                CapabilityBlocked, "PROBE_REF_EXCLUSIVITY_UNVERIFIED"
            ):
                run_sandbox_push_pr(REPO, "t" * 32, PROBE, push_only=True)
            pushed.assert_not_called()
            forbidden.assert_not_called()

    def test_existing_remote_probe_ref_fails_before_a_write(self):
        def existing(app, method, suffix, payload=None):
            if suffix.startswith("/pulls?"):
                return {"items": []}
            if suffix.startswith("/branches/"):
                return {"commit": {"sha": SHA}}
            raise AssertionError(suffix)
        with patch.object(
            SandboxApp, "verify_installation",
            return_value={"default_branch": "main"},
        ), patch.object(
            SandboxApp, "_repo_api", autospec=True, side_effect=existing
        ), patch("sandbox_app_capabilities.push_canary") as pushed:
            with self.assertRaisesRegex(
                CapabilityBlocked, "PROBE_RECONCILIATION_REQUIRES_IMMUTABLE_PROOF"
            ):
                run_sandbox_push_pr(REPO, "t" * 32, PROBE, push_only=True)
            pushed.assert_not_called()

    def test_cli_modes_are_mutually_exclusive(self):
        with patch.object(
            sys, "argv", [
                "sandbox_app_capabilities.py", "--sandbox-repo", REPO,
                "--push-pr", "--push-only", "--probe-id", PROBE,
            ],
        ), self.assertRaises(SystemExit) as ex:
            main()
        self.assertEqual(ex.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
