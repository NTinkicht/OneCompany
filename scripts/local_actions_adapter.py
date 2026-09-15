#!/usr/bin/env python3
"""Reviewed unattended adapter for the zero-spend local GitHub Actions worker."""
from __future__ import annotations

import json
import re
import subprocess
import time
from typing import Any, Callable

from onecompany_lib import CONTROL, load_json

WORKFLOW_FILE = "onecompany-local-readonly.yml"
MECHANISM_ID = "onecompany-actions-readonly"
ACTOR_ID = "onecompany-local"
CAPABILITY = "repository_intelligence"
SAFE_TOKEN = re.compile(r"^[A-Za-z0-9._:-]{1,160}$")
FAILURE_CONCLUSIONS = {
    "failure",
    "cancelled",
    "timed_out",
    "action_required",
    "startup_failure",
    "stale",
}

Runner = Callable[..., subprocess.CompletedProcess[str]]
Sleeper = Callable[[float], None]
Clock = Callable[[], float]


def zero_spend_policy_reasons(budget: dict[str, Any]) -> list[str]:
    """Return hard reasons that make the free Actions worker ineligible."""
    ai = budget.get("ai", {})
    reasons: list[str] = []
    required = {
        "additional_monthly_spend_cap": 0,
        "allow_paid_fallback": False,
        "allow_overage": False,
        "allow_auto_topup": False,
        "allow_new_paid_vendor": False,
    }
    for key, expected in required.items():
        if ai.get(key) != expected:
            reasons.append(f"zero_spend_policy:{key}")
    allowed = set(budget.get("cost_classes", {}).get("allowed", []))
    if "FREE_ALLOWANCE" not in allowed:
        reasons.append("free_allowance_not_budget_allowed")
    return reasons


def validate_request(request: dict[str, Any]) -> list[str]:
    """Fail closed unless the request matches the exact read-only local path."""
    reasons: list[str] = []
    mechanism = request.get("mechanism")
    if request.get("actor") != ACTOR_ID:
        reasons.append("local_adapter_actor_mismatch")
    if request.get("capability") != CAPABILITY:
        reasons.append("local_adapter_capability_not_allowlisted")
    if request.get("unattended") is not True:
        reasons.append("local_adapter_requires_unattended_dispatch")
    if request.get("lease") is not None:
        reasons.append("local_readonly_adapter_rejects_lease_authority")
    if not isinstance(mechanism, dict):
        reasons.append("local_adapter_mechanism_missing")
    else:
        if mechanism.get("id") != MECHANISM_ID:
            reasons.append("local_adapter_mechanism_mismatch")
        if mechanism.get("kind") != "github_action":
            reasons.append("local_adapter_kind_mismatch")
        if mechanism.get("unattended") is not True:
            reasons.append("local_adapter_mechanism_not_unattended")
    repository = request.get("repository")
    if not isinstance(repository, str) or repository.count("/") != 1:
        reasons.append("local_adapter_repository_invalid")
    for field in ("dispatch_id", "work_unit"):
        value = request.get(field)
        if not isinstance(value, str) or not SAFE_TOKEN.fullmatch(value):
            reasons.append(f"local_adapter_{field}_invalid")
    reasons.extend(zero_spend_policy_reasons(load_json(CONTROL / "budget.json")))
    return sorted(set(reasons))


def _run(
    args: list[str],
    *,
    runner: Runner,
    timeout: float = 30.0,
) -> subprocess.CompletedProcess[str]:
    return runner(
        args,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def require_public_repository(
    repository: str, *, runner: Runner = subprocess.run
) -> None:
    """Revalidate the billing property that makes standard hosted runners free."""
    completed = _run(
        ["gh", "api", f"/repos/{repository}", "--jq", ".private"],
        runner=runner,
    )
    if (completed.stdout or "").strip().lower() != "false":
        raise RuntimeError("local_actions_requires_public_repository")


def list_worker_runs(repository: str, *, runner: Runner = subprocess.run) -> list[dict[str, Any]]:
    """Read the complete retained workflow-run history without mutating state."""
    completed = _run(
        [
            "gh",
            "api",
            "--paginate",
            "--slurp",
            f"/repos/{repository}/actions/workflows/{WORKFLOW_FILE}/runs?per_page=100",
        ],
        runner=runner,
    )
    pages = json.loads(completed.stdout or "[]")
    if not isinstance(pages, list):
        raise RuntimeError("local_actions_run_pages_not_list")

    runs: list[dict[str, Any]] = []
    for page in pages:
        if not isinstance(page, dict):
            raise RuntimeError("local_actions_run_page_invalid")
        page_runs = page.get("workflow_runs")
        if not isinstance(page_runs, list):
            raise RuntimeError("local_actions_run_page_missing_runs")
        for item in page_runs:
            if not isinstance(item, dict):
                raise RuntimeError("local_actions_run_item_invalid")
            runs.append(
                {
                    "databaseId": item.get("id"),
                    "displayTitle": item.get("display_title"),
                    "event": item.get("event"),
                    "status": item.get("status"),
                    "conclusion": item.get("conclusion"),
                    "url": item.get("html_url"),
                    "headSha": item.get("head_sha"),
                    "createdAt": item.get("created_at"),
                }
            )
    return runs


def _matching_run(runs: list[dict[str, Any]], dispatch_id: str) -> dict[str, Any] | None:
    title = f"OneCompany Local {dispatch_id}"
    matching = [
        item
        for item in runs
        if item.get("event") == "workflow_dispatch"
        and item.get("displayTitle") == title
    ]
    if not matching:
        return None
    return sorted(
        matching,
        key=lambda item: (
            str(item.get("createdAt") or ""),
            int(item.get("databaseId") or 0),
        ),
    )[0]


def _outcome_from_run(run: dict[str, Any]) -> dict[str, Any]:
    run_id = run.get("databaseId")
    url = run.get("url")
    if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id <= 0:
        raise RuntimeError("local_actions_run_id_invalid")
    if not isinstance(url, str) or not url.startswith("https://github.com/"):
        raise RuntimeError("local_actions_run_url_invalid")
    status = str(run.get("status") or "")
    conclusion = run.get("conclusion")
    evidence = {
        "provider": "github-actions-standard-public",
        "workflow": WORKFLOW_FILE,
        "run_id": run_id,
        "run_url": url,
        "run_status": status,
        "conclusion": conclusion,
        "head_sha": run.get("headSha"),
        "display_title": run.get("displayTitle"),
    }
    if status == "completed":
        if conclusion == "success":
            return {"status": "DISPATCH_COMPLETED", "evidence": evidence}
        if conclusion in FAILURE_CONCLUSIONS or conclusion:
            raise RuntimeError(f"local_actions_run_failed:{conclusion}")
        raise RuntimeError("local_actions_completed_without_conclusion")
    if status in {"queued", "in_progress", "pending", "waiting", "requested"}:
        return {"status": "DISPATCH_STARTED", "evidence": evidence}
    raise RuntimeError(f"local_actions_run_status_unknown:{status}")


def dispatch_workflow(request: dict[str, Any], *, runner: Runner = subprocess.run) -> None:
    """Request the exact reviewed local workflow on protected main."""
    repository = str(request["repository"])
    _run(
        [
            "gh",
            "api",
            "--method",
            "POST",
            f"/repos/{repository}/actions/workflows/{WORKFLOW_FILE}/dispatches",
            "-f",
            "ref=main",
            "-f",
            f"inputs[dispatch_id]={request['dispatch_id']}",
            "-f",
            f"inputs[work_unit]={request['work_unit']}",
            "-f",
            f"inputs[capability]={request['capability']}",
        ],
        runner=runner,
    )


def invoke(
    request: dict[str, Any],
    *,
    runner: Runner = subprocess.run,
    sleeper: Sleeper = time.sleep,
    clock: Clock = time.monotonic,
    poll_attempts: int = 12,
    poll_delay_seconds: float = 0.5,
    poll_timeout_seconds: float = 30.0,
    max_poll_delay_seconds: float = 4.0,
) -> dict[str, Any]:
    """Start or reconcile one provider-side idempotent read-only Actions run."""
    reasons = validate_request(request)
    if reasons:
        raise RuntimeError(";".join(reasons))

    repository = str(request["repository"])
    dispatch_id = str(request["dispatch_id"])
    require_public_repository(repository, runner=runner)

    existing = _matching_run(list_worker_runs(repository, runner=runner), dispatch_id)
    if existing is not None:
        return _outcome_from_run(existing)

    dispatch_workflow(request, runner=runner)
    attempts = max(1, int(poll_attempts))
    delay = max(0.0, float(poll_delay_seconds))
    deadline = clock() + max(0.0, float(poll_timeout_seconds))
    max_delay = max(delay, float(max_poll_delay_seconds))

    for attempt in range(attempts):
        found = _matching_run(list_worker_runs(repository, runner=runner), dispatch_id)
        if found is not None:
            return _outcome_from_run(found)

        if attempt + 1 >= attempts:
            break
        remaining = deadline - clock()
        if remaining <= 0:
            break
        sleep_for = min(delay, remaining)
        if sleep_for > 0:
            sleeper(sleep_for)
        if delay > 0:
            delay = min(max_delay, delay * 2)

    raise RuntimeError("local_actions_run_evidence_not_observed")
