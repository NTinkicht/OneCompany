#!/usr/bin/env python3
"""Verify exact-SHA deterministic checks against base-trusted CompanyOS policy."""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from typing import Any
from urllib.parse import quote

from onecompany_lib import CONTROL, command_exists, load_json, run

RUN_ID_RE = re.compile(r"/actions/runs/(\d+)(?:/|$)")
MANIFEST_PATH = ".onecompany/required-checks.json"


def required_check_manifest() -> dict[str, Any]:
    return load_json(CONTROL / "required-checks.json")


def required_check_names() -> list[str]:
    return [
        str(item.get("name"))
        for item in required_check_manifest().get("checks", [])
        if item.get("name")
    ]


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


def _contents(repo: str, path: str, ref: str) -> tuple[dict[str, Any] | None, str | None]:
    encoded_path = quote(path, safe="/")
    encoded_ref = quote(ref, safe="")
    return _gh_json(f"repos/{repo}/contents/{encoded_path}?ref={encoded_ref}")


def _manifest_from_ref(repo: str, ref: str) -> tuple[dict[str, Any] | None, str | None]:
    payload, error = _contents(repo, MANIFEST_PATH, ref)
    if payload is None:
        return None, error or f"cannot load trusted required-check manifest at {ref}"
    if payload.get("encoding") != "base64" or not isinstance(payload.get("content"), str):
        return None, f"trusted required-check manifest at {ref} is not decodable base64 content"
    try:
        text = base64.b64decode(payload["content"]).decode("utf-8")
        manifest = json.loads(text)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"trusted required-check manifest at {ref} is invalid: {exc}"
    if not isinstance(manifest, dict):
        return None, f"trusted required-check manifest at {ref} is not an object"
    return manifest, None


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


def _workflow_pr_binding(
    workflow: dict[str, Any],
    sha: str,
    trusted_ref: str,
) -> tuple[bool, int | None, str | None]:
    """Require the Actions run to name the exact PR head/base tuple.

    Exact head alone is insufficient: a branch can retain the same head commit
    while the target branch advances. GitHub's workflow-run pull_requests payload
    is platform evidence of the base against which this check actually ran.
    """
    pulls = workflow.get("pull_requests")
    if not isinstance(pulls, list) or not pulls:
        return False, None, "trusted check workflow has no pull-request base binding"
    for item in pulls:
        if not isinstance(item, dict):
            continue
        head = (item.get("head") or {}).get("sha")
        base = (item.get("base") or {}).get("sha")
        number = item.get("number")
        if head == sha and base == trusted_ref:
            return True, number if isinstance(number, int) else None, None
    return (
        False,
        None,
        f"trusted check workflow is not bound to exact head/base {sha}/{trusted_ref}",
    )


def _trusted_matches(
    repo: str,
    sha: str,
    spec: dict[str, Any],
    runs: list[dict[str, Any]],
    trusted_ref: str | None,
) -> tuple[list[tuple[dict[str, Any], dict[str, Any], int | None]], list[str]]:
    name = str(spec.get("name") or "")
    app_slug = spec.get("app_slug")
    workflow_path = str(spec.get("workflow_path") or "")
    trusted: list[tuple[dict[str, Any], dict[str, Any], int | None]] = []
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
                f"check {item.get('id')} named {name!r} came from untrusted workflow "
                f"{workflow.get('path')!r}"
            )
            continue
        if workflow.get("head_sha") != sha:
            rejected.append(
                f"workflow run for check {item.get('id')} is not bound to exact SHA {sha}"
            )
            continue
        pr_number: int | None = None
        if trusted_ref:
            bound, pr_number, binding_error = _workflow_pr_binding(workflow, sha, trusted_ref)
            if not bound:
                rejected.append(
                    binding_error
                    or f"workflow run for check {item.get('id')} is not bound to reviewed base"
                )
                continue
        trusted.append((item, workflow, pr_number))
    return trusted, rejected


def _verify_trusted_workflow_unchanged(
    repo: str,
    workflow_path: str,
    trusted_ref: str,
    candidate_sha: str,
) -> tuple[bool, str | None, str | None]:
    base_payload, base_error = _contents(repo, workflow_path, trusted_ref)
    if base_payload is None:
        return False, None, base_error or f"trusted workflow {workflow_path} missing at {trusted_ref}"
    candidate_payload, candidate_error = _contents(repo, workflow_path, candidate_sha)
    if candidate_payload is None:
        return False, None, candidate_error or f"candidate workflow {workflow_path} missing at {candidate_sha}"
    base_blob = base_payload.get("sha")
    candidate_blob = candidate_payload.get("sha")
    if not isinstance(base_blob, str) or not base_blob:
        return False, None, f"trusted workflow {workflow_path} has no blob identity at {trusted_ref}"
    if candidate_blob != base_blob:
        return (
            False,
            base_blob,
            f"trusted workflow {workflow_path} changed relative to base {trusted_ref}; "
            "candidate CI cannot self-attest that change",
        )
    return True, base_blob, None


def evaluate_required_checks(
    repo: str,
    sha: str,
    trusted_ref: str | None = None,
) -> tuple[bool, list[str], list[dict[str, Any]]]:
    """Return whether every required check passed on exact head and reviewed base."""
    if trusted_ref:
        manifest, manifest_error = _manifest_from_ref(repo, trusted_ref)
        if manifest is None:
            return False, [manifest_error or "cannot load base-trusted required-check manifest"], []
    else:
        manifest = required_check_manifest()

    required = manifest.get("checks", [])
    if not required:
        return False, ["required-check manifest is empty"], []

    workflow_blobs: dict[str, str] = {}
    reasons: list[str] = []
    if trusted_ref:
        for spec in required:
            workflow_path = str(spec.get("workflow_path") or "")
            if not workflow_path:
                reasons.append("base-trusted required check is missing workflow_path")
                continue
            unchanged, blob_sha, workflow_error = _verify_trusted_workflow_unchanged(
                repo, workflow_path, trusted_ref, sha
            )
            if blob_sha:
                workflow_blobs[workflow_path] = blob_sha
            if not unchanged:
                reasons.append(
                    workflow_error or f"trusted workflow {workflow_path} could not be verified"
                )
        if reasons:
            return False, reasons, []

    runs, error = _check_runs(repo, sha)
    if runs is None:
        return False, [error or "cannot read check runs"], []

    evidence: list[dict[str, Any]] = []
    for spec in required:
        name = str(spec.get("name") or "")
        allowed = {str(value) for value in spec.get("allowed_conclusions", [])}
        trusted, rejected = _trusted_matches(repo, sha, spec, runs, trusted_ref)
        if not trusted:
            reasons.append(f"required trusted check missing on exact head/base: {name}")
            reasons.extend(rejected)
            continue
        observed, workflow, pr_number = max(
            trusted, key=lambda triple: int(triple[0].get("id") or 0)
        )
        status = observed.get("status")
        conclusion = observed.get("conclusion")
        workflow_path = str(spec.get("workflow_path") or "")
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
            "workflow_pr": pr_number,
            "workflow_base_sha": trusted_ref,
            "trusted_ref": trusted_ref,
            "trusted_workflow_blob_sha": workflow_blobs.get(workflow_path),
        }
        evidence.append(record)
        if observed.get("head_sha") != sha:
            reasons.append(f"required check {name} is not bound to exact SHA {sha}")
        if status != "completed":
            reasons.append(f"required check {name} is not completed (status={status})")
        if conclusion not in allowed:
            reasons.append(
                f"required check {name} conclusion {conclusion!r} not in {sorted(allowed)}"
            )
    return not reasons, reasons, evidence


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify CompanyOS required checks on an exact commit SHA"
    )
    parser.add_argument("--repo", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument(
        "--trusted-ref",
        help="Base/trusted revision that defines the required-check manifest and workflow",
    )
    args = parser.parse_args()
    ok, reasons, evidence = evaluate_required_checks(
        args.repo, args.sha, trusted_ref=args.trusted_ref
    )
    print(
        json.dumps(
            {
                "ok": ok,
                "sha": args.sha,
                "trusted_ref": args.trusted_ref,
                "checks": evidence,
                "reasons": reasons,
            },
            indent=2,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
