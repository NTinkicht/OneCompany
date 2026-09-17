from __future__ import annotations

import json
import os
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
CONTROL = ROOT / ".onecompany"
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import ledger_lib  # noqa: E402


def top_level_permissions(path: Path) -> dict[str, str]:
    """Parse the workflow's top-level permissions mapping without YAML dependencies."""
    lines = path.read_text(encoding="utf-8").splitlines()
    mapping: dict[str, str] = {}
    in_permissions = False
    for line in lines:
        if not in_permissions:
            if line == "permissions:":
                in_permissions = True
            continue
        if line and not line.startswith(" "):
            break
        match = re.fullmatch(r"  ([A-Za-z0-9_-]+):\s*([^\s#]+)\s*(?:#.*)?", line)
        if match:
            mapping[match.group(1)] = match.group(2)
    return mapping


class B1LedgerActivationTests(unittest.TestCase):
    """Regress B1 authority while allowing later B2/B3 liveness activation."""

    def setUp(self):
        if os.environ.get("ONECOMPANY_OFFLINE_UNIT_FIXTURE") == "1":
            self.skipTest("B1 activation is exercised separately from the offline unit fixture")
        self.config = json.loads((CONTROL / "config.json").read_text(encoding="utf-8"))
        repository = self.config.get("project", {}).get("repository")
        if repository != "NTinkicht/OneCompany":
            self.skipTest("B1 activation evidence is specific to the OneCompany source repository")
        self.ledger = json.loads((CONTROL / "ledger.json").read_text(encoding="utf-8"))
        self.supervision = json.loads((CONTROL / "supervision.json").read_text(encoding="utf-8"))

    def test_team_room_is_activated_with_minimal_verified_publisher_set(self):
        self.assertTrue(self.ledger["enabled"])
        self.assertEqual(self.ledger["issue_number"], 45)
        self.assertEqual(self.ledger["trusted_publisher_logins"], ["NTinkicht"])
        self.assertEqual(self.ledger["event_format_version"], 2)
        self.assertEqual(self.ledger["legacy_event_max_comment_id"], 0)
        self.assertTrue(self.ledger["required_for_autonomous_merge"])
        self.assertTrue(self.ledger["required_for_continuous_autonomy"])

    def test_automation_publishers_are_not_trusted_in_b1(self):
        trusted = set(self.ledger["trusted_publisher_logins"])
        self.assertNotIn("github-actions[bot]", trusted)
        self.assertNotIn("coderabbitai[bot]", trusted)
        self.assertNotIn("chatgpt-codex-connector[bot]", trusted)
        self.assertNotIn("dependabot[bot]", trusted)

    def test_later_supervision_activation_does_not_expand_b1_authority(self):
        self.assertTrue(self.supervision["enabled"])
        self.assertEqual(self.supervision["mode"], "notify")
        self.assertEqual(self.supervision["coordination"]["team_room_issue_number"], 45)
        self.assertTrue(self.supervision["github_actions"]["enabled"])
        self.assertTrue(self.supervision["github_actions"]["may_post_team_room"])
        self.assertFalse(self.supervision["github_actions"]["may_failover"])
        self.assertFalse(self.supervision["github_actions"]["may_merge"])
        self.assertFalse(self.supervision["chatgpt_tasks"]["may_mutate"])
        self.assertEqual(self.ledger["trusted_publisher_logins"], ["NTinkicht"])

    def test_read_smoke_is_read_only_and_uses_one_immutable_snapshot(self):
        workflow = ROOT / ".github" / "workflows" / "onecompany-ledger-read-smoke.yml"
        self.assertTrue(workflow.exists())
        text = workflow.read_text(encoding="utf-8")
        self.assertEqual(top_level_permissions(workflow), {"contents": "read", "issues": "read"})
        self.assertIn("persist-credentials: false", text)
        self.assertIn(".unlink(missing_ok=True)", text)
        self.assertEqual(text.count("issues/45/comments?per_page=100"), 1)
        self.assertIn("trusted-events.json", text)
        self.assertIn("canonical ledger replay changed after local cache deletion", text)
        self.assertIn("feature checkout unexpectedly acquired durable-ledger authority", text)
        self.assertIn("b1-human-publisher-proof-20260915", text)
        self.assertIn('proof.get("github_publisher") != "NTinkicht"', text)

    def test_validation_workflow_has_exact_read_only_permissions(self):
        workflow = ROOT / ".github" / "workflows" / "onecompany-validate.yml"
        self.assertEqual(top_level_permissions(workflow), {"contents": "read", "issues": "read"})
        text = workflow.read_text(encoding="utf-8")
        self.assertNotIn("write-all", text)
        self.assertNotRegex(text, r"(?m)^\s{2,}[A-Za-z0-9_-]+:\s*write\s*$")

    def test_runtime_activation_guard_requires_current_protected_tip(self):
        head = "a" * 40

        def fake_run(command, cwd=None):
            del cwd
            if command[:3] == ["git", "diff", "--quiet"]:
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            if command == ["git", "rev-parse", "HEAD"]:
                return SimpleNamespace(returncode=0, stdout=head + "\n", stderr="")
            raise AssertionError(f"unexpected command: {command}")

        with (
            patch.object(ledger_lib, "run", side_effect=fake_run),
            patch.object(ledger_lib, "_repository", return_value="NTinkicht/OneCompany"),
            patch.object(ledger_lib, "_default_branch_tip", return_value=("main", head)) as tip,
        ):
            ledger_lib._assert_ledger_runtime_activation()
        tip.assert_called_once_with("NTinkicht/OneCompany")

    def test_runtime_activation_guard_rejects_feature_or_stale_checkout(self):
        protected_tip = "f" * 40
        for label, checkout in (("feature-ref", "e" * 40), ("older-main", "d" * 40)):
            with self.subTest(label=label):
                def fake_run(command, cwd=None):
                    del cwd
                    if command[:3] == ["git", "diff", "--quiet"]:
                        return SimpleNamespace(returncode=0, stdout="", stderr="")
                    if command == ["git", "rev-parse", "HEAD"]:
                        return SimpleNamespace(returncode=0, stdout=checkout + "\n", stderr="")
                    raise AssertionError(f"unexpected command: {command}")

                with (
                    patch.object(ledger_lib, "run", side_effect=fake_run),
                    patch.object(ledger_lib, "_repository", return_value="NTinkicht/OneCompany"),
                    patch.object(ledger_lib, "_default_branch_tip", return_value=("main", protected_tip)),
                ):
                    with self.assertRaisesRegex(RuntimeError, "current protected default-branch tip"):
                        ledger_lib._assert_ledger_runtime_activation()

    def test_runtime_activation_guard_rejects_dirty_policy_before_network(self):
        with (
            patch.object(ledger_lib, "run", return_value=SimpleNamespace(returncode=1, stdout="", stderr="")),
            patch.object(ledger_lib, "_repository") as repository,
        ):
            with self.assertRaisesRegex(RuntimeError, "clean ledger/config policy"):
                ledger_lib._assert_ledger_runtime_activation()
        repository.assert_not_called()

    def test_zero_extra_spend_and_human_sovereignty_remain_unchanged(self):
        budget = json.loads((CONTROL / "budget.json").read_text(encoding="utf-8"))
        ai = budget["ai"]
        self.assertEqual(ai["additional_monthly_spend_cap"], 0)
        self.assertFalse(ai["allow_paid_fallback"])
        self.assertFalse(ai["allow_overage"])
        self.assertFalse(ai["allow_auto_topup"])
        self.assertFalse(ai["allow_new_paid_vendor"])
        self.assertTrue(self.config["autonomy"]["human_must_approve_autonomy_increase"])
        self.assertIn("increase_autonomy_level", self.config["human_only_decisions"])
        self.assertIn("change_budget_policy", self.config["human_only_decisions"])
        self.assertIn("add_or_expand_credentials", self.config["human_only_decisions"])


if __name__ == "__main__":
    unittest.main()
