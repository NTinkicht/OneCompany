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

import copilot_actions_adapter as adapter  # noqa: E402


class CopilotActionsAdapterTests(unittest.TestCase):
    """Regress the A3b provider boundary without spending AI credits."""

    def good_budget(self):
        return {
            "ai": {
                "additional_monthly_spend_cap": 0,
                "allow_paid_fallback": False,
                "allow_overage": False,
                "allow_auto_topup": False,
                "allow_new_paid_vendor": False,
            },
            "cost_classes": {"allowed": ["INCLUDED_SUBSCRIPTION"]},
        }

    def request(self):
        return {
            "dispatch_id": "dispatch-a3b-test",
            "repository": "NTinkicht/OneCompany",
            "work_unit": "WU-A3B",
            "actor": "github-copilot",
            "capability": "repository_intelligence",
            "mechanism": {
                "id": "copilot-actions-readonly",
                "kind": "github_action",
                "unattended": True,
            },
            "lease": None,
            "unattended": True,
        }

    def completed(self, args, stdout=""):
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")

    def api_run(self, run):
        return {
            "id": run["databaseId"],
            "display_title": run["displayTitle"],
            "status": run["status"],
            "conclusion": run.get("conclusion"),
            "html_url": run["url"],
            "head_sha": run.get("headSha"),
            "created_at": run["createdAt"],
        }

    def paginated(self, *pages):
        return json.dumps(
            [{"workflow_runs": [self.api_run(run) for run in page]} for page in pages]
        )

    def test_zero_spend_policy_rejects_any_paid_escape_hatch(self):
        budget = self.good_budget()
        self.assertEqual(adapter.zero_spend_policy_reasons(budget), [])
        for key, value in (
            ("additional_monthly_spend_cap", 1),
            ("allow_paid_fallback", True),
            ("allow_overage", True),
            ("allow_auto_topup", True),
            ("allow_new_paid_vendor", True),
        ):
            changed = json.loads(json.dumps(budget))
            changed["ai"][key] = value
            self.assertTrue(adapter.zero_spend_policy_reasons(changed), key)

    def test_request_is_exactly_readonly_unattended_copilot(self):
        with patch.object(adapter, "load_json", return_value=self.good_budget()):
            self.assertEqual(adapter.validate_request(self.request()), [])
            mutations = [
                ("actor", "chatgpt"),
                ("capability", "implementation"),
                ("unattended", False),
                ("lease", {"id": "lease-1"}),
                ("repository", "invalid"),
            ]
            for key, value in mutations:
                request = self.request()
                request[key] = value
                self.assertTrue(adapter.validate_request(request), key)

            request = self.request()
            request["mechanism"] = dict(request["mechanism"], id="other")
            self.assertTrue(adapter.validate_request(request))
            request = self.request()
            request["mechanism"] = dict(request["mechanism"], kind="local_cli")
            self.assertTrue(adapter.validate_request(request))

    def test_existing_provider_run_is_reconciled_without_second_dispatch(self):
        request = self.request()
        run = {
            "databaseId": 101,
            "displayTitle": "OneCompany Copilot dispatch-a3b-test",
            "status": "in_progress",
            "conclusion": None,
            "url": "https://github.com/NTinkicht/OneCompany/actions/runs/101",
            "headSha": "a" * 40,
            "createdAt": "2026-09-16T00:00:00Z",
        }
        calls: list[list[str]] = []

        def runner(args, **_kwargs):
            calls.append(args)
            if args[0:4] == ["gh", "api", "--paginate", "--slurp"]:
                return self.completed(args, self.paginated([run]))
            raise AssertionError(args)

        with patch.object(adapter, "load_json", return_value=self.good_budget()):
            result = adapter.invoke(request, runner=runner, sleeper=lambda _: None)
        self.assertEqual(result["status"], "DISPATCH_STARTED")
        self.assertEqual(result["evidence"]["run_id"], 101)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0:4], ["gh", "api", "--paginate", "--slurp"])

    def test_matching_run_beyond_first_hundred_is_reconciled_without_post(self):
        request = self.request()
        first_page = [
            {
                "databaseId": 2000 + index,
                "displayTitle": f"OneCompany Copilot unrelated-{index}",
                "status": "completed",
                "conclusion": "success",
                "url": f"https://github.com/NTinkicht/OneCompany/actions/runs/{2000 + index}",
                "headSha": "d" * 40,
                "createdAt": f"2026-09-16T00:{index // 60:02d}:{index % 60:02d}Z",
            }
            for index in range(100)
        ]
        older_match = {
            "databaseId": 88,
            "displayTitle": "OneCompany Copilot dispatch-a3b-test",
            "status": "in_progress",
            "conclusion": None,
            "url": "https://github.com/NTinkicht/OneCompany/actions/runs/88",
            "headSha": "e" * 40,
            "createdAt": "2026-09-15T23:00:00Z",
        }
        calls: list[list[str]] = []

        def runner(args, **_kwargs):
            calls.append(args)
            if args[0:4] == ["gh", "api", "--paginate", "--slurp"]:
                return self.completed(args, self.paginated(first_page, [older_match]))
            raise AssertionError(args)

        with patch.object(adapter, "load_json", return_value=self.good_budget()):
            result = adapter.invoke(request, runner=runner, sleeper=lambda _: None)
        self.assertEqual(result["evidence"]["run_id"], 88)
        self.assertFalse(any(call[0:3] == ["gh", "api", "--method"] for call in calls))
        self.assertIn("per_page=100", calls[0][-1])

    def test_dispatch_uses_exact_main_workflow_and_returns_run_evidence(self):
        request = self.request()
        run = {
            "databaseId": 202,
            "displayTitle": "OneCompany Copilot dispatch-a3b-test",
            "status": "queued",
            "conclusion": None,
            "url": "https://github.com/NTinkicht/OneCompany/actions/runs/202",
            "headSha": "b" * 40,
            "createdAt": "2026-09-16T00:00:01Z",
        }
        calls: list[list[str]] = []
        listings = iter([self.paginated([]), self.paginated([run])])

        def runner(args, **_kwargs):
            calls.append(args)
            if args[0:4] == ["gh", "api", "--paginate", "--slurp"]:
                return self.completed(args, next(listings))
            if args[0:3] == ["gh", "api", "--method"]:
                return self.completed(args, "")
            raise AssertionError(args)

        with patch.object(adapter, "load_json", return_value=self.good_budget()):
            result = adapter.invoke(request, runner=runner, sleeper=lambda _: None)
        self.assertEqual(result["status"], "DISPATCH_STARTED")
        post = next(call for call in calls if call[0:3] == ["gh", "api", "--method"])
        self.assertIn("ref=main", post)
        self.assertIn("inputs[dispatch_id]=dispatch-a3b-test", post)
        self.assertIn("inputs[work_unit]=WU-A3B", post)
        self.assertIn("inputs[capability]=repository_intelligence", post)
        self.assertIn(adapter.WORKFLOW_FILE, " ".join(post))

    def test_completed_success_and_failure_are_not_retried(self):
        base = {
            "databaseId": 303,
            "displayTitle": "OneCompany Copilot dispatch-a3b-test",
            "status": "completed",
            "url": "https://github.com/NTinkicht/OneCompany/actions/runs/303",
            "headSha": "c" * 40,
            "createdAt": "2026-09-16T00:00:00Z",
        }
        request = self.request()

        def success_runner(args, **_kwargs):
            return self.completed(args, self.paginated([{**base, "conclusion": "success"}]))

        with patch.object(adapter, "load_json", return_value=self.good_budget()):
            result = adapter.invoke(request, runner=success_runner, sleeper=lambda _: None)
        self.assertEqual(result["status"], "DISPATCH_COMPLETED")

        def failure_runner(args, **_kwargs):
            return self.completed(args, self.paginated([{**base, "conclusion": "failure"}]))

        with patch.object(adapter, "load_json", return_value=self.good_budget()):
            with self.assertRaisesRegex(RuntimeError, "copilot_actions_run_failed"):
                adapter.invoke(request, runner=failure_runner, sleeper=lambda _: None)

    def test_missing_run_evidence_fails_closed(self):
        request = self.request()

        def runner(args, **_kwargs):
            if args[0:4] == ["gh", "api", "--paginate", "--slurp"]:
                return self.completed(args, self.paginated([]))
            if args[0:3] == ["gh", "api", "--method"]:
                return self.completed(args, "")
            raise AssertionError(args)

        with patch.object(adapter, "load_json", return_value=self.good_budget()):
            with self.assertRaisesRegex(RuntimeError, "run_evidence_not_observed"):
                adapter.invoke(
                    request,
                    runner=runner,
                    sleeper=lambda _: None,
                    poll_attempts=2,
                    poll_delay_seconds=0,
                )

    def test_workflow_is_pinned_readonly_and_credit_bounded(self):
        workflow = ROOT / ".github" / "workflows" / "onecompany-copilot-readonly.yml"
        if not workflow.exists():
            self.skipTest(
                "repo-specific dormant Copilot workflow is intentionally absent from a fresh bootstrap"
            )
        text = workflow.read_text(encoding="utf-8")
        self.assertIn("contents: read", text)
        self.assertIn("actions: read", text)
        self.assertIn("copilot-requests: write", text)
        self.assertNotIn("contents: write", text)
        self.assertIn("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", text)
        self.assertIn("actions/setup-node@820762786026740c76f36085b0efc47a31fe5020", text)
        self.assertIn("COPILOT_SCOPE: '@github'", text)
        self.assertIn("COPILOT_PACKAGE: copilot", text)
        self.assertIn("COPILOT_VERSION: '1.0.83'", text)
        self.assertIn('npm install --global "${COPILOT_SCOPE}/${COPILOT_PACKAGE}@${COPILOT_VERSION}"', text)
        self.assertIn("--max-ai-credits=30", text)
        self.assertIn("--available-tools='view,grep,glob'", text)
        self.assertIn("--allow-tool='read'", text)
        self.assertIn("--no-custom-instructions", text)
        self.assertIn("--no-auto-update", text)
        self.assertNotIn("--yolo", text)
        self.assertNotIn("--allow-all", text)
        self.assertIn("Refuse duplicate workflow-dispatch AI invocation", text)
        self.assertIn("gh api --paginate --slurp", text)
        self.assertIn("workflow_runs.extend(page['workflow_runs'])", text)
        self.assertIn("canonical = min(", text)
        self.assertIn("current workflow run is missing from duplicate-election evidence", text)
        self.assertIn("key=lambda item: (item['created_at'], int(item['id']))", text)


if __name__ == "__main__":
    unittest.main()
