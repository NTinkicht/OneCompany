from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import local_actions_adapter as adapter  # noqa: E402


class LocalActionsAdapterTests(unittest.TestCase):
    """Regress the free public-runner A3b execution boundary."""

    def good_budget(self):
        return {
            "ai": {
                "additional_monthly_spend_cap": 0,
                "allow_paid_fallback": False,
                "allow_overage": False,
                "allow_auto_topup": False,
                "allow_new_paid_vendor": False,
            },
            "cost_classes": {"allowed": ["FREE_ALLOWANCE"]},
        }

    def request(self):
        return {
            "dispatch_id": "dispatch-local-a3b",
            "repository": "NTinkicht/OneCompany",
            "work_unit": "WU-A3B-LOCAL",
            "actor": "onecompany-local",
            "capability": "repository_intelligence",
            "mechanism": {
                "id": "onecompany-actions-readonly",
                "kind": "github_action",
                "unattended": True,
            },
            "lease": None,
            "unattended": True,
        }

    def completed(self, args, stdout=""):
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")

    def test_policy_and_request_fail_closed(self):
        with patch.object(adapter, "load_json", return_value=self.good_budget()):
            self.assertEqual(adapter.validate_request(self.request()), [])
            for key, value in (
                ("actor", "github-copilot"),
                ("capability", "implementation"),
                ("unattended", False),
                ("lease", {"id": "lease-1"}),
                ("repository", "invalid"),
            ):
                request = self.request()
                request[key] = value
                self.assertTrue(adapter.validate_request(request), key)

        changed = self.good_budget()
        changed["ai"]["allow_overage"] = True
        self.assertTrue(adapter.zero_spend_policy_reasons(changed))

    def test_private_repository_is_rejected_before_dispatch(self):
        def runner(args, **_kwargs):
            return self.completed(args, "true\n")

        with self.assertRaisesRegex(RuntimeError, "requires_public_repository"):
            adapter.require_public_repository("NTinkicht/OneCompany", runner=runner)

    def test_existing_provider_run_reconciles_without_post(self):
        request = self.request()
        run = {
            "databaseId": 401,
            "displayTitle": "OneCompany Local dispatch-local-a3b",
            "status": "in_progress",
            "conclusion": None,
            "url": "https://github.com/NTinkicht/OneCompany/actions/runs/401",
            "headSha": "d" * 40,
            "createdAt": "2026-09-16T00:00:00Z",
        }
        calls: list[list[str]] = []

        def runner(args, **_kwargs):
            calls.append(args)
            if args[0:2] == ["gh", "api"] and "--jq" in args:
                return self.completed(args, "false\n")
            if args[0:3] == ["gh", "run", "list"]:
                return self.completed(args, json.dumps([run]))
            raise AssertionError(args)

        with patch.object(adapter, "load_json", return_value=self.good_budget()):
            result = adapter.invoke(request, runner=runner, sleeper=lambda _: None)
        self.assertEqual(result["status"], "DISPATCH_STARTED")
        self.assertEqual(result["evidence"]["run_id"], 401)
        self.assertFalse(any(call[0:3] == ["gh", "api", "--method"] for call in calls))

    def test_dispatches_exact_main_workflow_and_observes_evidence(self):
        request = self.request()
        run = {
            "databaseId": 402,
            "displayTitle": "OneCompany Local dispatch-local-a3b",
            "status": "queued",
            "conclusion": None,
            "url": "https://github.com/NTinkicht/OneCompany/actions/runs/402",
            "headSha": "e" * 40,
            "createdAt": "2026-09-16T00:00:01Z",
        }
        listings = iter([[], [run]])
        calls: list[list[str]] = []

        def runner(args, **_kwargs):
            calls.append(args)
            if args[0:2] == ["gh", "api"] and "--jq" in args:
                return self.completed(args, "false\n")
            if args[0:3] == ["gh", "run", "list"]:
                return self.completed(args, json.dumps(next(listings)))
            if args[0:3] == ["gh", "api", "--method"]:
                return self.completed(args, "")
            raise AssertionError(args)

        with patch.object(adapter, "load_json", return_value=self.good_budget()):
            result = adapter.invoke(request, runner=runner, sleeper=lambda _: None)
        self.assertEqual(result["status"], "DISPATCH_STARTED")
        post = next(call for call in calls if call[0:3] == ["gh", "api", "--method"])
        self.assertIn("ref=main", post)
        self.assertIn("inputs[dispatch_id]=dispatch-local-a3b", post)
        self.assertIn("inputs[work_unit]=WU-A3B-LOCAL", post)
        self.assertIn("inputs[capability]=repository_intelligence", post)
        self.assertIn(adapter.WORKFLOW_FILE, " ".join(post))

    def test_completed_failure_never_becomes_retryable_success(self):
        request = self.request()
        run = {
            "databaseId": 403,
            "displayTitle": "OneCompany Local dispatch-local-a3b",
            "status": "completed",
            "conclusion": "failure",
            "url": "https://github.com/NTinkicht/OneCompany/actions/runs/403",
            "headSha": "f" * 40,
            "createdAt": "2026-09-16T00:00:00Z",
        }

        def runner(args, **_kwargs):
            if args[0:2] == ["gh", "api"] and "--jq" in args:
                return self.completed(args, "false\n")
            return self.completed(args, json.dumps([run]))

        with patch.object(adapter, "load_json", return_value=self.good_budget()):
            with self.assertRaisesRegex(RuntimeError, "local_actions_run_failed"):
                adapter.invoke(request, runner=runner, sleeper=lambda _: None)

    def test_workflow_is_readonly_public_runner_guarded_and_deduplicated(self):
        text = (ROOT / ".github" / "workflows" / "onecompany-local-readonly.yml").read_text(encoding="utf-8")
        self.assertIn("contents: read", text)
        self.assertIn("actions: read", text)
        self.assertNotIn("contents: write", text)
        self.assertNotIn("copilot-requests", text)
        self.assertIn("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", text)
        self.assertIn("FREE_ALLOWANCE", text)
        self.assertIn("Standard hosted-runner zero-spend proof requires a public repository", text)
        self.assertIn("Refuse duplicate workflow-dispatch execution", text)
        self.assertIn("persist-credentials: false", text)


if __name__ == "__main__":
    unittest.main()
