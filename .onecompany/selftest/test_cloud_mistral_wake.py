"""Source-only assertions: Mistral cloud wake cannot quietly become a paid writer."""
from __future__ import annotations

import json
import re
import tempfile
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
        workflow_path = str(WORKFLOW.relative_to(ROOT))
        self.assertIn(workflow_path, bootstrap.SOURCE_INSTALLATION_EXCLUSIONS)
        self.assertNotIn(workflow_path, bootstrap.COPY_PATHS)
        with tempfile.TemporaryDirectory() as dirname:
            destination = Path(dirname)
            (destination / ".github" / "workflows").mkdir(parents=True)
            bootstrap.copy_item(
                ROOT / ".github" / "workflows", destination / ".github" / "workflows",
                False, destination,
            )
            self.assertFalse((destination / workflow_path).exists())

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


    def test_effective_wake_structure_and_every_external_action_sha(self):
        # Check active YAML lines rather than matching strings in comments.
        content = WORKFLOW.read_text(encoding="utf-8")
        active = "\n".join(
            line for line in content.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
        for expected in (
            "on:",
            "  issue_comment:",
            "    types: [created]",
            "permissions:",
            "  contents: read",
            "  issues: write",
            "  pull-requests: read",
            "  actions: read",
            "  mistral-vibe:",
        ):
            self.assertIn(expected, active.splitlines())
        guard = re.search(
            r"(?m)^    if: >-\n((?:      [^\n]+\n)+)",
            active + "\n",
        )
        self.assertIsNotNone(guard)
        condition = guard.group(1)
        for expected in (
            "github.event.issue.number == 130",
            "github.event.issue.pull_request == null",
            "github.actor == 'NTinkicht'",
            "contains(github.event.comment.body, '@mistral-vibe')",
        ):
            self.assertIn(expected, condition)
        self.assertEqual(len(re.findall(r"(?m)^    if: >-$", active)), 1)
        uses = re.findall(r"(?m)^\s+-?\s*uses:\s*(\S+)\s*$", active)
        self.assertEqual(len(uses), 2, uses)
        for reference in uses:
            self.assertRegex(reference, r"^actions/[a-z0-9-]+@[0-9a-f]{40}$")
        self.assertNotRegex(active, r"(?m)^\s+(?:contents|pull-requests): write$")
        self.assertNotRegex(active, r"(?m)^  pull_request_target:")

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
            'elif [[ "$code" == "124" || "$code" == "137" ]]; then',
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
