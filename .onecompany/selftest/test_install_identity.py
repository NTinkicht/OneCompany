from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import install_identity


class InstallIdentityTests(unittest.TestCase):
    def test_org_owner_requires_explicit_human_root_and_code_owner(self):
        with patch.object(
            install_identity,
            "repository_owner_info",
            return_value=({"login": "acme-org", "type": "Organization"}, None),
        ):
            with self.assertRaisesRegex(ValueError, "organization-owned repositories require"):
                install_identity.resolve_install_principals(
                    "acme-org/project",
                    code_owner=None,
                    root_principal=None,
                )

    def test_org_owner_accepts_explicit_team_and_human_root_without_inference(self):
        with patch.object(install_identity, "repository_owner_info") as owner_info:
            code_owner, root = install_identity.resolve_install_principals(
                "acme-org/project",
                code_owner="@acme-org/reviewers",
                root_principal="alice",
            )
        owner_info.assert_not_called()
        self.assertEqual(code_owner, "@acme-org/reviewers")
        self.assertEqual(root, "alice")

    def test_user_owner_may_be_safe_default_for_both_principals(self):
        with patch.object(
            install_identity,
            "repository_owner_info",
            return_value=({"login": "octocat", "type": "User"}, None),
        ):
            code_owner, root = install_identity.resolve_install_principals(
                "octocat/project",
                code_owner=None,
                root_principal=None,
            )
        self.assertEqual(code_owner, "@octocat")
        self.assertEqual(root, "octocat")


if __name__ == "__main__":
    unittest.main()
