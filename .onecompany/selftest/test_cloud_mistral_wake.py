"""Source-only assertions: Mistral cloud wake cannot quietly become a paid writer."""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import bootstrap

WORKFLOW = ROOT / ".github/workflows/onecompany-mistral-vibe-wake.yml"
DISPATCH = ROOT / ".onecompany/dispatch.json"
READINESS = ROOT / ".onecompany/readiness.json"


class MistralCloudWakeTests(unittest.TestCase):
    def test_wake_is_source_only_and_not_in_fresh_installation(self):
        self.assertIn("docs/CLOUD-AGENT-QUALIFICATION.md", bootstrap.SOURCE_ONLY_PLANNING_FILES)
        self.assertNotIn(str(WORKFLOW.relative_to(ROOT)), bootstrap.COPY_PATHS)

    def test_actions_wake_is_owner_and_issue_bound(self):
        content = WORKFLOW.read_text(encoding="utf-8")
        for expected in (
            "github.event.issue.number == 130",
            "github.event.issue.pull_request == null",
            "github.actor == 'NTinkicht'",
            "contains(github.event.comment.body, '@mistral-vibe')",
            "runs-on: ubuntu-latest",
            "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
            "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
            "persist-credentials: false",
        ):
            self.assertIn(expected, content)
        self.assertNotIn("pull_request_target:", content)
        self.assertNotIn("write-all", content)
        self.assertNotIn("XAI_API_KEY", content)

    def test_read_only_model_tools_and_cost_guards(self):
        content = WORKFLOW.read_text(encoding="utf-8")
        for expected in (
            "ONECOMPANY_MISTRAL_PAYG_DISABLED_CONFIRMED",
            "additional_monthly_spend_cap",
            "allow_paid_fallback",
            "allow_overage",
            "allow_auto_topup",
            "allow_new_paid_vendor",
            "MISTRAL_API_KEY",
            "https://console.mistral.ai/api/vibe/whoami",
            "mistral-vibe==2.25.3",
            "--agent plan",
            "--enabled-tools grep",
            "--enabled-tools read_file",
            "enabled_tools = [\"grep\", \"read_file\"]",
            "timeout --signal=TERM --kill-after=15s 600s",
            "AUTH_BLOCKED",
            "CONFIG_BLOCKED",
            "CAPACITY_DEGRADED",
            "TOKEN_BUDGET_EXCEEDED",
            "[REDACTED]",
            "gh issue comment 130",
        ):
            self.assertIn(expected, content)
        self.assertNotIn("contents: write", content)
        self.assertNotIn("pull-requests: write", content)
        self.assertNotIn("gh pr merge", content)

    def test_dispatch_does_not_falsely_activate_unproven_roles(self):
        dispatch = json.loads(DISPATCH.read_text(encoding="utf-8"))
        actors = {item["actor_id"]: item["mechanisms"] for item in dispatch["actors"]}
        mistral = {m["id"]: m for m in actors["mistral-vibe"]}
        grok = {m["id"]: m for m in actors["grok-4-6-interactive"]}
        for mechanism in (
            mistral["vibe-readonly-wake"],
            mistral["vibe-exact-head-review"],
            mistral["vibe-lease-implementation"],
            grok["grok-supergrok-cloud-wake"],
        ):
            self.assertFalse(mechanism["configured"])
        self.assertEqual(mistral["vibe-readonly-wake"]["capabilities"],
                         ["repository_intelligence", "test_design", "failure_analysis", "documentation", "research"])

    def test_readiness_not_inflated_by_workflow_presence(self):
        readiness = json.loads(READINESS.read_text(encoding="utf-8"))
        by_actor = {a["actor_id"]: a for a in readiness["actors"]}
        mistral = by_actor["mistral-vibe"]
        self.assertEqual(mistral["verified_capabilities"], [])
        self.assertFalse(mistral["unattended"]["verified"])
        grok = by_actor["grok-4-6-interactive"]
        self.assertEqual(grok["verified_capabilities"], ["repository_intelligence"])
        self.assertFalse(grok["unattended"]["verified"])


if __name__ == "__main__":
    unittest.main()
