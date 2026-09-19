#!/usr/bin/env python3
"""Read-only, run-bound verifier for two disposable A4 installations.

The actual producer result is recovered from the successful GitHub Actions
job's immutable log, never trusted from a self-asserted manifest field.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from a4_pr_producer import GitHub, Refused, SHA, REPO, branch_for, fixture_body

EVIDENCE_PREFIX = "A4_PRODUCER_EVIDENCE:"
WORKFLOW_PATH = ".github/workflows/onecompany-a4-pr-producer.yml"
PRODUCER_JOB = "bounded-first-pr"
PRODUCER_STEP = "Reserve one branch and create or reconcile one fixture PR"
# Both constants live in the verifier source, never in the pilot manifest.
TRUSTED_CI_WORKFLOW_PATH = ".github/workflows/onecompany-a4-fixture-validation.yml"
TRUSTED_CI_WORKFLOW_BLOB = "8480f5c8bd94187efe3ccb1effa9def51d15addd"
TRUSTED_CI_CHECK_NAME = "validate-fixture"


class _SafeLogRedirect(urllib.request.HTTPRedirectHandler):
    """Drop repository token on GitHub's signed, cross-host log redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise Refused("github_job_log_redirect_not_https")
        if urllib.parse.urlsplit(newurl).hostname != "api.github.com":
            redirected.remove_header("Authorization")
            redirected.remove_header("authorization")
        return redirected


def _job_log(api: GitHub, job_id: int) -> str:
    """Fetch the GitHub-hosted job log with a bounded, token-safe redirect."""
    if not isinstance(job_id, int) or isinstance(job_id, bool) or job_id <= 0:
        raise Refused("producer_job_id_invalid")
    request = urllib.request.Request(
        f"https://api.github.com/repos/{api.repository}/actions/jobs/{job_id}/logs",
        headers={
            "Authorization": "Bearer " + api.token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.build_opener(_SafeLogRedirect()).open(
            request, timeout=20
        ) as response:
            raw = response.read(2_000_001)
    except (OSError, urllib.error.HTTPError, ValueError) as exc:
        raise Refused("github_job_log_unavailable") from exc
    if len(raw) > 2_000_000:
        raise Refused("github_job_log_too_large")
    return _decode_job_log(raw)


def _decode_job_log(raw: bytes) -> str:
    """Accept GitHub's job-log zip archive, or a raw UTF-8 log body."""
    if raw.startswith(b"PK"):
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                parts: list[str] = []
                for name in archive.namelist():
                    if name.endswith("/"):
                        continue
                    parts.append(archive.read(name).decode("utf-8"))
        except (OSError, UnicodeError, zipfile.BadZipFile, RuntimeError) as exc:
            raise Refused("github_job_log_not_utf8") from exc
        if not parts:
            raise Refused("github_job_log_empty")
        return "\n".join(parts)
    try:
        return raw.decode("utf-8")
    except UnicodeError as exc:
        raise Refused("github_job_log_not_utf8") from exc


def _job_evidence(log: str) -> dict[str, Any]:
    """Accept one complete JSON producer result from a job log, not prose."""
    matching = [
        line.split(EVIDENCE_PREFIX, 1)[1].strip()
        for line in log.splitlines()
        if EVIDENCE_PREFIX in line
    ]
    if len(matching) != 1:
        raise Refused("producer_job_evidence_missing_or_ambiguous")
    try:
        record = json.loads(matching[0])
    except (ValueError, TypeError) as exc:
        raise Refused("producer_job_evidence_invalid_json") from exc
    if not isinstance(record, dict):
        raise Refused("producer_job_evidence_not_object")
    return record


def verify_installation(entry: dict, token: str) -> dict:
    """Verify fixture-only diff, producer job provenance and exact-head CI."""
    repo = entry["repository"]
    wu = entry["work_unit"]
    actor = entry["actor"]
    head = entry["head"]
    base = entry["base"]
    number = entry["pr"]
    run_id = entry["workflow_run"]
    check_name = entry["check_name"]
    ci_workflow_path = entry["ci_workflow_path"]
    ci_run_id = entry["ci_workflow_run"]
    branch = branch_for(wu)
    if not all(isinstance(value, str) and value for value in
               (repo, actor, check_name)) or not REPO.fullmatch(repo):
        raise Refused("manifest_identity_missing")
    if not SHA.fullmatch(head) or not SHA.fullmatch(base):
        raise Refused("manifest_exact_sha_missing")
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise Refused("manifest_pr_invalid")
    if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id < 1:
        raise Refused("manifest_run_invalid")
    if ci_workflow_path != TRUSTED_CI_WORKFLOW_PATH or check_name != TRUSTED_CI_CHECK_NAME:
        raise Refused("manifest_ci_workflow_not_approved")
    if (not isinstance(ci_run_id, int) or isinstance(ci_run_id, bool)
        or ci_run_id < 1 or not isinstance(ci_workflow_path, str)
        or not re.fullmatch(r"\.github/workflows/[A-Za-z0-9_.-]+\.yml", ci_workflow_path)):
        raise Refused("manifest_ci_workflow_invalid")
    api = GitHub(repo, token)
    meta = api.call("GET", "/")
    pr = api.call("GET", "/pulls/" + str(number))
    if (pr.get("head", {}).get("sha") != head
        or pr.get("head", {}).get("ref") != branch
        or pr.get("head", {}).get("repo", {}).get("full_name") != repo
        or pr.get("base", {}).get("sha") != base
        or pr.get("base", {}).get("ref") != meta.get("default_branch")
        or pr.get("base", {}).get("repo", {}).get("full_name") != repo):
        raise Refused("manifest_pr_not_exact_live_identity")
    original = fixture_body(repo, wu, actor, base)
    commit = api.call("GET", "/git/commits/" + head)
    if (len(commit.get("parents", [])) != 1
        or commit["parents"][0].get("sha") != base):
        raise Refused("manifest_not_initial_fixture_claim")
    target = "docs/onecompany-fixture/" + wu + ".md"
    comparison = api.call("GET", "/compare/" + base + "..." + head)
    changed = comparison.get("files")
    if (comparison.get("status") != "ahead"
        or comparison.get("total_commits") != 1
        or comparison.get("truncated") is True
        or not isinstance(changed, list)
        or len(changed) != 1
        or changed[0].get("filename") != target
        or changed[0].get("status") != "added"):
        raise Refused("manifest_commit_changes_outside_fixture")
    content = api.call("GET", "/contents/" + target + "?ref=" + head)
    try:
        encoded = content["content"]
        if not isinstance(encoded, str) or content.get("encoding") != "base64":
            raise ValueError("unexpected_contents_encoding")
        normalized = re.sub(r"[ \t\r\n]", "", encoded)
        actual = base64.b64decode(normalized, validate=True).decode("utf-8")
    except (KeyError, UnicodeError, ValueError) as exc:
        raise Refused("manifest_fixture_unreadable") from exc
    if actual != original:
        raise Refused("manifest_fixture_content_not_exact")
    run = api.call("GET", "/actions/runs/" + str(run_id))
    if (run.get("id") != run_id
        or run.get("event") != "repository_dispatch"
        or run.get("path") != WORKFLOW_PATH
        or run.get("head_sha") != base
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
        or run.get("repository", {}).get("full_name") != repo):
        raise Refused("unattended_project_run_not_proven")
    jobs = api.call(
        "GET", "/actions/runs/" + str(run_id) + "/jobs?per_page=100"
    ).get("jobs", [])
    if not isinstance(jobs, list) or len(jobs) >= 100:
        raise Refused("producer_job_inventory_ambiguous")
    matched = [
        job for job in jobs
        if job.get("name") == PRODUCER_JOB and job.get("run_id") == run_id
    ]
    if len(matched) != 1:
        raise Refused("producer_job_missing_or_ambiguous")
    job = matched[0]
    if (job.get("status") != "completed"
        or job.get("conclusion") != "success"
        or not any(
            step.get("name") == PRODUCER_STEP
            and step.get("status") == "completed"
            and step.get("conclusion") == "success"
            for step in job.get("steps", [])
        )):
        raise Refused("producer_job_not_successful")
    record = _job_evidence(_job_log(api, job.get("id")))
    expected = {
        "status": "PR_CREATED_OR_RECONCILED",
        "repository": repo, "work_unit": wu, "actor": actor,
        "branch": branch, "pr": number, "head": head,
        "base": base, "fixture_path": target,
        "run_id": run_id, "run_attempt": run.get("run_attempt"),
    }
    if not isinstance(expected["run_attempt"], int) or any(
        record.get(key) != value for key, value in expected.items()
    ):
        raise Refused("producer_job_evidence_identity_mismatch")
    workflow_at_base = api.call(
        "GET", "/contents/" + ci_workflow_path + "?ref=" + base
    )
    if workflow_at_base.get("type") != "file":
        raise Refused("trusted_ci_workflow_missing_from_base")
    if workflow_at_base.get("sha") != TRUSTED_CI_WORKFLOW_BLOB:
        raise Refused("trusted_ci_workflow_blob_mismatch")
    if meta.get("private") is not False or meta.get("visibility") != "public":
        raise Refused("public_disposable_runner_requirement_not_proven")
    checks = api.call("GET", "/commits/" + head + "/check-runs?per_page=100")
    rows = checks.get("check_runs", [])
    if not isinstance(rows, list) or len(rows) >= 100:
        raise Refused("exact_head_ci_inventory_ambiguous")
    trusted_url = re.compile(
        r"https://github\.com/" + re.escape(repo)
        + r"/actions/runs/" + str(ci_run_id) + r"/job/[0-9]+/?$"
    )
    matching = [
        item for item in rows
        if isinstance(item, dict) and item.get("name") == check_name
        and item.get("head_sha") == head
        and item.get("status") == "completed"
        and item.get("conclusion") == "success"
        and isinstance(item.get("app"), dict)
        and item["app"].get("slug") == "github-actions"
        and isinstance(item.get("details_url"), str)
        and trusted_url.fullmatch(item["details_url"])
    ]
    if len(matching) != 1:
        raise Refused("exact_head_ci_not_proven")
    ci_run = api.call("GET", "/actions/runs/" + str(ci_run_id))
    if (ci_run.get("id") != ci_run_id
        or ci_run.get("head_sha") != head
        or ci_run.get("path") != ci_workflow_path
        or ci_run.get("status") != "completed"
        or ci_run.get("conclusion") != "success"
        or ci_run.get("repository", {}).get("full_name") != repo):
        raise Refused("trusted_exact_head_ci_run_not_proven")
    return {
        "repository": repo, "work_unit": wu, "pr": number,
        "head": head, "base": base, "workflow_run": run_id,
        "producer_job": job["id"], "check_name": check_name,
        "ci_workflow_path": ci_workflow_path, "ci_workflow_run": ci_run_id,
        "result": "DISPOSABLE_A4_UNATTENDED_CREATION_CI_VERIFIED",
        "review_and_merge": "separate independent gates, not attested by A4",
    }


def verify_pair(entries: list[dict], token: str) -> dict:
    """Require two distinct owners and independently authenticated run data."""
    if not isinstance(entries, list) or len(entries) != 2:
        raise Refused("exactly_two_installations_required")
    repos = [entry.get("repository") for entry in entries]
    if not all(isinstance(repo, str) and REPO.fullmatch(repo)
               for repo in repos):
        raise Refused("installations_repository_identity_invalid")
    if repos[0].split("/", 1)[0].casefold() == repos[1].split("/", 1)[0].casefold():
        raise Refused("installations_must_have_distinct_owners")
    outcomes = [verify_installation(entry, token) for entry in entries]
    return {
        "result": "TWO_REAL_ISOLATED_A4_PILOTS_VERIFIED",
        "installations": outcomes,
    }


def main() -> int:
    """Validate a non-secret manifest using read-only GitHub API access."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "manifest", type=Path,
        help="JSON array of two non-secret disposable-pilot records",
    )
    args = parser.parse_args()
    try:
        data = json.loads(args.manifest.read_text(encoding="utf-8"))
        result = verify_pair(data, os.environ.get("GH_TOKEN", ""))
    except (Refused, OSError, ValueError, KeyError, TypeError) as exc:
        print("A4_QUALIFICATION_REFUSED: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
