import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import grok_cloud_qualification as q


class GrokCloudQualificationTests(unittest.TestCase):
    def test_current_repo_state_is_explicit_capacity_blocked(self):
        result = q.classify()
        self.assertEqual(result["status"], "CAPACITY_BLOCKED")
        self.assertFalse(result["configured"])
        self.assertEqual(result["capabilities"], [])
        self.assertEqual(result["reason"], "PROVIDER_CLOUD_EXECUTION_NOT_VERIFIED")
        self.assertIn("do not export OAuth", result["owner_action_required"])

    def test_unverified_mechanism_cannot_be_silently_enabled(self):
        unsafe = {
            "id": q.TARGET_MECHANISM,
            "kind": "event_trigger",
            "configured": True,
            "unattended": True,
            "capabilities": ["code_review"],
        }
        with patch.object(q, "mechanism", return_value=unsafe), self.assertRaisesRegex(
            ValueError, "UNVERIFIED_GROK_ROUTE_MUST_REMAIN_DISABLED"
        ):
            q.classify()

    def test_structural_manifest_never_self_promotes_capability(self):
        evidence = {
            "repo": q.REPO,
            "issue": q.ISSUE,
            "codespace_off": True,
            "human_prompt_required": False,
            "zero_additional_spend": True,
            "metered_api_used": False,
            "provider_execution_id": "provider-run-123456",
            "github_publisher": q.BOT_LOGIN,
            "github_comment_url": (
                "https://github.com/NTinkicht/OneCompany/issues/131#issuecomment-12345"
            ),
            "head_sha": "a" * 40,
        }
        result = q.classify(evidence)
        self.assertEqual(result["status"], "LIVE_VERIFICATION_REQUIRED")
        self.assertFalse(result["configured"])
        self.assertEqual(result["capabilities"], [])
        self.assertEqual(
            result["reason"], "STRUCTURAL_EVIDENCE_CANNOT_SELF_PROMOTE_CAPABILITY"
        )

    def test_paid_or_manual_or_wrong_publisher_evidence_is_rejected(self):
        base = {
            "repo": q.REPO,
            "issue": q.ISSUE,
            "codespace_off": True,
            "human_prompt_required": False,
            "zero_additional_spend": True,
            "metered_api_used": False,
            "provider_execution_id": "provider-run-123456",
            "github_publisher": q.BOT_LOGIN,
            "github_comment_url": (
                "https://github.com/NTinkicht/OneCompany/issues/131#issuecomment-12345"
            ),
            "head_sha": "b" * 40,
        }
        for key, value in (
            ("metered_api_used", True),
            ("human_prompt_required", True),
            ("codespace_off", False),
            ("github_publisher", "NTinkicht"),
        ):
            sample = dict(base)
            sample[key] = value
            with self.subTest(key=key), self.assertRaisesRegex(
                ValueError, "GROK_CLOUD_EVIDENCE_INVALID"
            ):
                q.classify(sample)


if __name__ == "__main__":
    unittest.main()
