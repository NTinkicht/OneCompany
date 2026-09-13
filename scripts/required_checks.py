#!/usr/bin/env python3
"""Verify exact-SHA deterministic checks against the versioned CompanyOS manifest."""
from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

from onecompany_lib import CONTROL, command_exists, load_json, run

RUN_ID_RE = re.compile(r"/actions/runs/(\d+)(?:/|$)")


def required_check_manifest() -> dict[str, Any]:
    return load_json(CONTROL / "required-checks.json")


def required_check_names() -> list[str]:
    return [str(item.get("name")) for item in required_check_manifest().get("checks", []) if item.get("name")]


def _gh_json(path: str) -> tuple[dict[str, Any] | None, str | None]:
    if not command_exists("gh"):
        return None, "gh CLI is required to verify GitHub evidence"
    result = run(["gh", "api", path, "-H", "Accept: application/vnd.github+json"])
    if result.returncode != 0:
        return None, result.stderr.strip() or result.stdout.strip() or f"GitHub query failed: {path}"
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return None, f"GitHub response was not valid JSON: {exc}"
    if not isinstance(value, dict):
        return None, f"GitHub response was not an object: {path}"
    return value, None


def _check_runs(repo: str, sha: str) -> tuple[list[dict[str, Any]] | None, str | None]:
    if not command_exists("gh"):
        return None, "gh CLI is required to verify check runs"
    result = run(
        [
            "gh",
            "api",
            "--paginate",
            "--slurp",
            f"repos/{repo}/commits/{sha}/check-runs?per_page=100",
            "-H",
            "Accept: application/vnd.github+json",
        ]
    )
    if result.returncode != 0:
        return None, result.stderr.strip() or result.stdout.strip() or "GitHub check-run query failed"
    try:
        pages = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return None, f"GitHub check-run response was not valid JSON: {exc}"
    if not isinstance(pages, list):
        pages = [pages]
    runs: list[dict[str, Any]] = []
    for page in pages:
        if isinstance(page, dict):
            items = page.get("check_runs", [])
            if isinstance(items, list):
                runs.extend(item for item in items if isinstance(item, dict))
    return runs, None


def _workflow_run(repo: str, check: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    details_url = str(check.get("details_url") or "")
    match = RUN_ID_RE.search(details_url)
    if not match:
        return None, f"check run {check.get('id')} is not linked to a GitHub Actions workflow run"
    return _gh_json(f"repos/{repo}/actions/runs/{match.group(1)}")


def _trusted_matches(
    repo: str,
    sha: str,
    spec: dict[str, Any],
    runs: list[dict[str, Any]],
) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]], list[str]]:
    name = str(spec.get("name") or "")
    app_slug = spec.get("app_slug")
    workflow_path = str(spec.get("workflow_path") or "")
    trusted: list[tuple[dict[str, Any], dict[str, Any]]] = []
    rejected: list[str] = []
    for item in runs:
        if item.get("name") != name:
            continue
        observed_slug = ((item.get("app") or {}).get("slug"))
        if app_slug and observed_slug != app_slug:
            continue
        workflow, error = _workflow_run(repo, item)
        if workflow is None:
            rejected.append(error or f"cannot resolve workflow for check {item.get('id')}")
            continue
        if workflow_path and workflow.get("path") != workflow_path:
            rejected.append(
                f"check {item.get('id')} named {name!r} came from untrusted workflow {workflow.get('path')!r}"
            )
            continue
        if workflow.get("head_sha") != sha:
            rejected.append(f"workflow run for check {item.get('id')} is not bound to exact SHA {sha}")
            continue
        trusted.append((item, workflow))
    return trusted, rejected


def evaluate_required_checks(repo: str, sha: str) -> tuple[bool, list[str], list[dict[str, Any]]]:
    """Return whether every manifest-required check passed on exactly ``sha``.

    Required evidence is bound to the exact check name, GitHub App, and trusted
    workflow path declared in the manifest. A same-name job emitted by another
    workflow is rejected rather than allowed to supersede the trusted referee.
    """
    manifest = required_check_manifest()
    required = manifest.get("checks", [])
    if not required:
        return False, ["required-check manifest is empty"], []
    runs, error = _check_runs(repo, sha)
    if runs is None:
        return False, [error or "cannot read check runs"], []

    reasons: list[str] = []
    evidence: list[dict[str, Any]] = []
    for spec in required:
        name = str(spec.get("name") or "")
        allowed = {str(value) for value in spec.get("allowed_conclusions", [])}
        trusted, rejected = _trusted_matches(repo, sha, spec, runs)
        if not trusted:
            reasons.append(f"required trusted check missing on exact SHA: {name}")
            reasons.extend(rejected)
            continue
        observed, workflow = max(trusted, key=lambda pair: int(pair[0].get("id") or 0))
        status = observed.get("status")
        conclusion = observed.get("conclusion")
        record = {
            "name": name,
            "id": observed.get("id"),
            "status": status,
            "conclusion": conclusion,
            "app_slug": ((observed.get("app") or {}).get("slug")),
            "details_url": observed.get("details_url"),
            "head_sha": observed.get("head_sha"),
            "workflow_run_id": workflow.get("id"),
            "workflow_path": workflow.get("path"),
            "workflow_event": workflow.get("event"),
        }
        evidence.append(record)
        if observed.get("head_sha") != sha:
            reasons.append(f"required check {name} is not bound to exact SHA {sha}")
        if status != "completed":
            reasons.append(f"required check {name} is not completed (status={status})")
        if conclusion not in allowed:
            reasons.append(f"required check {name} conclusion {conclusion!r} not in {sorted(allowed)}")
    return not reasons, reasons, evidence


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify CompanyOS required checks on an exact commit SHA")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--sha", required=True)
    args = parser.parse_args()
    ok, reasons, evidence = evaluate_required_checks(args.repo, args.sha)
    print(json.dumps({"ok": ok, "sha": args.sha, "checks": evidence, "reasons": reasons}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
