from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import ledger as ledger_cli


class PrivilegedLedgerIdentityTests(unittest.TestCase):
    def _run(self, *args: str) -> int:
        with patch.object(sys, "argv", ["ledger.py", *args]):
            return ledger_cli.main()

    def test_root_rotation_requires_trusted_ref_before_any_publication(self):
        with patch.object(ledger_cli, "post_event") as post:
            rc = self._run(
                "post",
                "--type",
                "ROOT_TRUST_ROTATED",
                "--actor",
                "human-owner",
                "--payload-json",
                "{}",
            )
        self.assertEqual(rc, 2)
        post.assert_not_called()

    def test_spoofed_human_owner_label_cannot_replace_platform_authorization(self):
        with (
            patch.object(ledger_cli, "load_json", return_value={"project": {"repository": "o/r"}}),
            patch.object(ledger_cli, "github_repo_from_config", return_value="o/r"),
            patch.object(
                ledger_cli,
                "authorize_current_principal",
                return_value=(None, ["platform principal 'worker' is unknown"]),
            ) as authorize,
            patch.object(ledger_cli, "post_event") as post,
        ):
            rc = self._run(
                "post",
                "--type",
                "ROOT_TRUST_ROTATED",
                "--trusted-ref",
                "b" * 40,
                "--actor",
                "human-owner",
                "--payload-json",
                "{}",
            )
        self.assertEqual(rc, 2)
        authorize.assert_called_once_with("o/r", "b" * 40, "root_rotation")
        post.assert_not_called()

    def test_authorized_rotation_uses_derived_actor_and_records_provenance(self):
        identity = {
            "login": "ActualOwner",
            "actor_id": "human-owner",
            "authorities": ["root_rotation"],
            "policy_provenance": {
                "source": "base",
                "trusted_ref": "b" * 40,
                "blob_sha": "c" * 40,
            },
        }
        event = {"event_id": "event-1", "type": "ROOT_TRUST_ROTATED"}
        with (
            patch.object(ledger_cli, "load_json", return_value={"project": {"repository": "o/r"}}),
            patch.object(ledger_cli, "github_repo_from_config", return_value="o/r"),
            patch.object(
                ledger_cli,
                "authorize_current_principal",
                return_value=(identity, []),
            ),
            patch.object(ledger_cli, "post_event", return_value=event) as post,
        ):
            rc = self._run(
                "post",
                "--type",
                "ROOT_TRUST_ROTATED",
                "--trusted-ref",
                "b" * 40,
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
        post.assert_called_once()
        event_type, actor, payload = post.call_args.args
        self.assertEqual(event_type, "ROOT_TRUST_ROTATED")
        self.assertEqual(actor, "human-owner")
        self.assertEqual(payload["platform_login"], "ActualOwner")
        self.assertEqual(payload["identity_policy_provenance"], identity["policy_provenance"])
        self.assertEqual(payload["previous_principal"], "OldOwner")

    def test_asserted_actor_must_match_derived_platform_identity(self):
        identity = {
            "login": "ActualOwner",
            "actor_id": "human-owner",
            "authorities": ["root_rotation"],
            "policy_provenance": {"source": "base", "trusted_ref": "b" * 40},
        }
        with (
            patch.object(ledger_cli, "load_json", return_value={"project": {"repository": "o/r"}}),
            patch.object(ledger_cli, "github_repo_from_config", return_value="o/r"),
            patch.object(
                ledger_cli,
                "authorize_current_principal",
                return_value=(identity, []),
            ),
            patch.object(ledger_cli, "post_event") as post,
        ):
            rc = self._run(
                "post",
                "--type",
                "ROOT_TRUST_ROTATED",
                "--trusted-ref",
                "b" * 40,
                "--actor",
                "attacker",
                "--payload-json",
                "{}",
            )
        self.assertEqual(rc, 2)
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
