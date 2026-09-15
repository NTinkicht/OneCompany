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

    def api_run(self, run):
        return {
            "id": run["databaseId"],
            "display_title": run["displayTitle"],
            "event": run.get("event", "workflow_dispatch"),
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

    def test_dispatch_tokens_are_validated_before_any_provider_call(self):
        for field, value in (
            ("dispatch_id", "contains space"),
            ("work_unit", "bad/slash"),
            ("dispatch_id", "x" * 161),
        ):
            request = self.request()
            request[field] = value

            def runner(*_args, **_kwargs):
                raise AssertionError("provider must not be called for invalid dispatch tokens")

            with patch.object(adapter, "load_json", return_value=self.good_budget()):
                reasons = adapter.validate_request(request)
                self.assertIn(f"local_adapter_{field}_invalid", reasons)
                with self.assertRaisesRegex(RuntimeError, f"local_adapter_{field}_invalid"):
                    adapter.invoke(request, runner=runner)

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
            if args[0:4] == ["gh", "api", "--paginate", "--slurp"]:
                return self.completed(args, self.paginated([run]))
            raise AssertionError(args)

        with patch.object(adapter, "load_json", return_value=self.good_budget()):
            result = adapter.invoke(request, runner=runner, sleeper=lambda _: None)
        self.assertEqual(result["status"], "DISPATCH_STARTED")
        self.assertEqual(result["evidence"]["run_id"], 401)
        history_call = next(
            call for call in calls if call[0:4] == ["gh", "api", "--paginate", "--slurp"]
        )
        self.assertNotIn("event=workflow_dispatch", history_call[-1])
        self.assertFalse(any(call[0:3] == ["gh", "api", "--method"] for call in calls))

    def test_non_dispatch_same_title_does_not_reconcile(self):
        push_run = {
            "databaseId": 400,
            "displayTitle": "OneCompany Local dispatch-local-a3b",
            "event": "push",
            "status": "completed",
            "conclusion": "success",
            "url": "https://github.com/NTinkicht/OneCompany/actions/runs/400",
            "headSha": "0" * 40,
            "createdAt": "2026-09-15T22:00:00Z",
        }
        normalized = adapter.list_worker_runs(
            "NTinkicht/OneCompany",
            runner=lambda args, **_kwargs: self.completed(args, self.paginated([push_run])),
        )
        self.assertIsNone(adapter._matching_run(normalized, "dispatch-local-a3b"))

    def test_matching_run_beyond_first_hundred_is_reconciled_without_post(self):
        request = self.request()
        first_page = [
            {
                "databaseId": 1000 + index,
                "displayTitle": f"OneCompany Local unrelated-{index}",
                "status": "completed",
                "conclusion": "success",
                "url": f"https://github.com/NTinkicht/OneCompany/actions/runs/{1000 + index}",
                "headSha": "a" * 40,
                "createdAt": f"2026-09-16T00:{index // 60:02d}:{index % 60:02d}Z",
            }
            for index in range(100)
        ]
        older_match = {
            "databaseId": 77,
            "displayTitle": "OneCompany Local dispatch-local-a3b",
            "status": "in_progress",
            "conclusion": None,
            "url": "https://github.com/NTinkicht/OneCompany/actions/runs/77",
            "headSha": "b" * 40,
            "createdAt": "2026-09-15T23:00:00Z",
        }
        calls: list[list[str]] = []

        def runner(args, **_kwargs):
            calls.append(args)
            if args[0:2] == ["gh", "api"] and "--jq" in args:
                return self.completed(args, "false\n")
            if args[0:4] == ["gh", "api", "--paginate", "--slurp"]:
                return self.completed(args, self.paginated(first_page, [older_match]))
            raise AssertionError(args)

        with patch.object(adapter, "load_json", return_value=self.good_budget()):
            result = adapter.invoke(request, runner=runner, sleeper=lambda _: None)
        self.assertEqual(result["evidence"]["run_id"], 77)
        self.assertFalse(any(call[0:3] == ["gh", "api", "--method"] for call in calls))
        history_call = next(
            call for call in calls if call[0:4] == ["gh", "api", "--paginate", "--slurp"]
        )
        self.assertIn("per_page=100", history_call[-1])
        self.assertNotIn("event=workflow_dispatch", history_call[-1])

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
        listings = iter([self.paginated([]), self.paginated([run])])
        calls: list[list[str]] = []

        def runner(args, **_kwargs):
            calls.append(args)
            if args[0:2] == ["gh", "api"] and "--jq" in args:
                return self.completed(args, "false\n")
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
        self.assertIn("inputs[dispatch_id]=dispatch-local-a3b", post)
        self.assertIn("inputs[work_unit]=WU-A3B-LOCAL", post)
        self.assertIn("inputs[capability]=repository_intelligence", post)
        self.assertIn(adapter.WORKFLOW_FILE, " ".join(post))

    def test_visibility_polling_uses_bounded_backoff_deadline(self):
        request = self.request()
        calls: list[list[str]] = []
        now = [0.0]
        sleeps: list[float] = []

        def clock():
            return now[0]

        def sleeper(seconds):
            sleeps.append(seconds)
            now[0] += seconds

        def runner(args, **_kwargs):
            calls.append(args)
            if args[0:2] == ["gh", "api"] and "--jq" in args:
                return self.completed(args, "false\n")
            if args[0:4] == ["gh", "api", "--paginate", "--slurp"]:
                return self.completed(args, self.paginated([]))
            if args[0:3] == ["gh", "api", "--method"]:
                return self.completed(args, "")
            raise AssertionError(args)

        with patch.object(adapter, "load_json", return_value=self.good_budget()):
            with self.assertRaisesRegex(RuntimeError, "local_actions_run_evidence_not_observed"):
                adapter.invoke(
                    request,
                    runner=runner,
                    sleeper=sleeper,
                    clock=clock,
                    poll_attempts=10,
                    poll_delay_seconds=1.0,
                    poll_timeout_seconds=2.5,
                    max_poll_delay_seconds=4.0,
                )

        self.assertEqual(sleeps, [1.0, 1.5])
        self.assertEqual(now[0], 2.5)
        list_calls = [
            call for call in calls if call[0:4] == ["gh", "api", "--paginate", "--slurp"]
        ]
        self.assertEqual(len(list_calls), 4)

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
            if args[0:4] == ["gh", "api", "--paginate", "--slurp"]:
                return self.completed(args, self.paginated([run]))
            raise AssertionError(args)

        with patch.object(adapter, "load_json", return_value=self.good_budget()):
            with self.assertRaisesRegex(RuntimeError, "local_actions_run_failed"):
                adapter.invoke(request, runner=runner, sleeper=lambda _: None)

    def test_workflow_is_readonly_public_runner_guarded_and_deduplicated(self):
        workflow = ROOT / ".github" / "workflows" / "onecompany-local-readonly.yml"
        if not workflow.exists():
            self.skipTest(
                "repo-specific A3b workflow is intentionally absent from a fresh bootstrap"
            )
        text = workflow.read_text(encoding="utf-8")
        self.assertIn("contents: read", text)
        self.assertIn("actions: read", text)
        self.assertNotIn("contents: write", text)
        self.assertNotIn("copilot-requests", text)
        self.assertIn("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", text)
        self.assertIn("FREE_ALLOWANCE", text)
        self.assertIn("Standard hosted-runner zero-spend proof requires a public repository", text)
        self.assertIn("Refuse duplicate workflow-dispatch execution", text)
        self.assertIn("persist-credentials: false", text)
        self.assertIn("gh api --paginate --slurp", text)
        self.assertNotIn("?event=workflow_dispatch", text)
        self.assertIn("item.get('event') == 'workflow_dispatch'", text)
        self.assertIn("workflow_runs.extend(page['workflow_runs'])", text)
        self.assertIn("canonical = min(", text)
        self.assertIn("current workflow run is missing from duplicate-election evidence", text)
        self.assertIn("key=lambda item: (item['created_at'], int(item['id']))", text)


if __name__ == "__main__":
    unittest.main()
