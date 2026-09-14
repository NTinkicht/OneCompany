from __future__ import annotations

import json
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import ledger as ledger_cli

TRUSTED = "b" * 40


class PrivilegedLedgerIdentityTests(unittest.TestCase):
    def _run(self, *args: str) -> int:
        with patch.object(sys, "argv", ["ledger.py", *args]):
            return ledger_cli.main()

    def _repo_context(self, stack: ExitStack) -> None:
        stack.enter_context(
            patch.object(
                ledger_cli,
                "load_json",
                return_value={"project": {"repository": "o/r"}},
            )
        )
        stack.enter_context(
            patch.object(ledger_cli, "github_repo_from_config", return_value="o/r")
        )
        stack.enter_context(
            patch.object(ledger_cli, "github_repo_from_remote", return_value="o/r")
        )
        stack.enter_context(
            patch.object(
                ledger_cli,
                "protected_default_branch_tip",
                return_value=(TRUSTED, []),
            )
        )

    def test_caller_selected_trust_ref_is_refused_before_authorization(self):
        with ExitStack() as stack:
            self._repo_context(stack)
            authorize = stack.enter_context(
                patch.object(ledger_cli, "authorize_current_principal")
            )
            post = stack.enter_context(patch.object(ledger_cli, "post_event"))
            rc = self._run(
                "post",
                "--type",
                "ROOT_TRUST_ROTATED",
                "--trusted-ref",
                "c" * 40,
                "--actor",
                "human-owner",
                "--payload-json",
                "{}",
            )
        self.assertEqual(rc, 2)
        authorize.assert_not_called()
        post.assert_not_called()

    def test_spoofed_human_owner_label_cannot_replace_platform_authorization(self):
        with ExitStack() as stack:
            self._repo_context(stack)
            authorize = stack.enter_context(
                patch.object(
                    ledger_cli,
                    "authorize_current_principal",
                    return_value=(None, ["platform principal 'worker' is unknown"]),
                )
            )
            post = stack.enter_context(patch.object(ledger_cli, "post_event"))
            rc = self._run(
                "post",
                "--type",
                "ROOT_TRUST_ROTATED",
                "--trusted-ref",
                TRUSTED,
                "--actor",
                "human-owner",
                "--payload-json",
                "{}",
            )
        self.assertEqual(rc, 2)
        authorize.assert_called_once_with("o/r", TRUSTED, "root_rotation")
        post.assert_not_called()

    def test_authorized_rotation_uses_protected_tip_and_records_provenance(self):
        identity = {
            "login": "ActualOwner",
            "actor_id": "human-owner",
            "authorities": ["root_rotation"],
            "policy_provenance": {
                "source": "base",
                "trusted_ref": TRUSTED,
                "blob_sha": "c" * 40,
            },
        }
        event = {"event_id": "event-1", "type": "ROOT_TRUST_ROTATED"}
        with ExitStack() as stack:
            self._repo_context(stack)
            authorize = stack.enter_context(
                patch.object(
                    ledger_cli,
                    "authorize_current_principal",
                    return_value=(identity, []),
                )
            )
            post = stack.enter_context(
                patch.object(ledger_cli, "post_event", return_value=event)
            )
            rc = self._run(
                "post",
                "--type",
                "ROOT_TRUST_ROTATED",
                "--trusted-ref",
                TRUSTED,
                "--actor",
                "ActualOwner",
                "--payload-json",
                json.dumps(
                    {
                        "previous_principal": "OldOwner",
                        "new_principal": "ActualOwner",
                        "reason": "scheduled rotation",
                    }
                ),
            )
        self.assertEqual(rc, 0)
        authorize.assert_called_once_with("o/r", TRUSTED, "root_rotation")
        post.assert_called_once()
        event_type, actor, payload = post.call_args.args
        self.assertEqual(event_type, "ROOT_TRUST_ROTATED")
        self.assertEqual(actor, "human-owner")
        self.assertEqual(payload["platform_login"], "ActualOwner")
        self.assertEqual(payload["identity_policy_provenance"], identity["policy_provenance"])
        self.assertEqual(payload["protected_trusted_ref"], TRUSTED)
        self.assertEqual(payload["previous_principal"], "OldOwner")

    def test_asserted_actor_must_match_derived_platform_identity(self):
        identity = {
            "login": "ActualOwner",
            "actor_id": "human-owner",
            "authorities": ["root_rotation"],
            "policy_provenance": {"source": "base", "trusted_ref": TRUSTED},
        }
        with ExitStack() as stack:
            self._repo_context(stack)
            stack.enter_context(
                patch.object(
                    ledger_cli,
                    "authorize_current_principal",
                    return_value=(identity, []),
                )
            )
            post = stack.enter_context(patch.object(ledger_cli, "post_event"))
            rc = self._run(
                "post",
                "--type",
                "ROOT_TRUST_ROTATED",
                "--trusted-ref",
                TRUSTED,
                "--actor",
                "attacker",
                "--payload-json",
                "{}",
            )
        self.assertEqual(rc, 2)
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
