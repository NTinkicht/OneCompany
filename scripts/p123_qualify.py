#!/usr/bin/env python3
"""Read-only P1/P2/P3 live-evidence campaign; never grants merge authority.

P1 delegates to the existing run-log-backed two-owner A4 verifier. P2 reports
real GitHub author attribution but NEVER treats a commit author string as
proof of authenticated GitHub App write permissions. P3 independently observes
failed CI -> exactly one bounded repair on the SAME PR -> green exact-head CI
-> distinct review -> GitHub merge -> owner-published durable MERGED event.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path
from typing import Any, Callable

from a4_pr_producer import GitHub, Refused, REPO, SHA, branch_for, fixture_body
from a4_qualify import (
    verify_pair, _positive_int, _require_object, _require_list, _job_log,
)
from l2_fixture_repair import (
    CI_PATH, CI_BLOB, REPAIR_LINE, REPAIR_PATH, REPAIR_JOB,
    REPAIR_STEP, EVIDENCE_PREFIX, FAILURE_MARKER,
)

# Installed disposable target must run exactly these reviewed base-trusted
# files, not candidate-selected workflow/script bytes.
REPAIR_WORKFLOW_BLOB = "3a5f18c5fa08c0a7ac79ccd04dc5da3de4b51aa2"
REPAIR_SCRIPT_BLOB = "3fb9581eb607ddf292506dc0ddf76d784bbdf1aa"

MARKER = "<!-- onecompany-ledger-v1 -->"
EVENT = re.compile(
    r"<!-- onecompany-ledger-v1 -->\s*```json\s*(\{.*?\})\s*```",
    re.DOTALL,
)
TRUSTED_CHECK = "validate-fixture"
MAX_EVENTS = 500


def _sha(entry: dict, name: str) -> str:
    value = entry.get(name)
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise Refused(name + "_not_exact_sha")
    return value


def _string(entry: dict, name: str) -> str:
    value = entry.get(name)
    if not isinstance(value, str) or not value:
        raise Refused(name + "_invalid")
    return value


def _content(api: GitHub, path: str, sha: str) -> tuple[str, dict]:
    record = _require_object(api.call(
        "GET", "/contents/" + urllib.parse.quote(path, safe="/")
        + "?ref=" + sha,
    ), "trusted_file_missing")
    encoded = record.get("content")
    if (record.get("type") != "file" or record.get("encoding") != "base64"
            or not isinstance(encoded, str)):
        raise Refused("trusted_file_invalid")
    try:
        raw = base64.b64decode(re.sub(r"\s", "", encoded), validate=True)
        if len(raw) > 128_000:
            raise ValueError("large")
        return raw.decode("utf-8"), record
    except (ValueError, UnicodeError, base64.binascii.Error):
        raise Refused("trusted_file_invalid") from None


def _run(api: GitHub, run_id: int, sha: str, conclusion: str) -> None:
    run = _require_object(api.call("GET", f"/actions/runs/{run_id}"),
                          "pilot_run_invalid")
    owner = _require_object(run.get("repository"), "pilot_run_invalid")
    if (owner.get("full_name") != api.repository
            or run.get("path") != CI_PATH
            or run.get("event") != "workflow_dispatch"
            or run.get("head_sha") != sha
            or run.get("status") != "completed"
            or run.get("conclusion") != conclusion):
        raise Refused("pilot_run_wrong_identity_or_conclusion")


def _check(api: GitHub, sha: str, run_id: int, conclusion: str) -> None:
    doc = _require_object(api.call(
        "GET", f"/commits/{sha}/check-runs?per_page=100",
    ), "pilot_checks_invalid")
    checks = _require_list(doc.get("check_runs"), "pilot_checks_invalid")
    if len(checks) >= 100:
        raise Refused("pilot_checks_truncated")
    matched = []
    for item in checks:
        if not isinstance(item, dict):
            raise Refused("pilot_check_malformed")
        app = item.get("app")
        details = item.get("details_url")
        if (item.get("name") == TRUSTED_CHECK
                and item.get("head_sha") == sha
                and item.get("status") == "completed"
                and item.get("conclusion") == conclusion
                and isinstance(app, dict)
                and app.get("slug") == "github-actions"
                and isinstance(details, str)
                and re.fullmatch(
                    rf"https://github\.com/{re.escape(api.repository)}"
                    rf"/actions/runs/{run_id}/job/\d+", details,
                )):
            matched.append(item)
    if len(matched) != 1:
        raise Refused("exact_head_ci_check_missing_or_ambiguous")


def _owner_merged_event(api: GitHub, base: str, *,
                        number: int, wu: str, repaired: str,
                        merge_sha: str) -> int:
    text, _ = _content(api, ".onecompany/ledger.json", base)
    try:
        policy = json.loads(text)
    except ValueError:
        raise Refused("trusted_ledger_invalid") from None
    if not isinstance(policy, dict) or policy.get("enabled") is not True:
        raise Refused("durable_ledger_not_enabled")
    issue = _positive_int(policy.get("issue_number"), "ledger_issue_invalid")
    publishers = policy.get("trusted_publisher_logins")
    if (not isinstance(publishers, list) or not publishers
            or not all(isinstance(p, str) and p for p in publishers)):
        raise Refused("trusted_ledger_publishers_invalid")
    events: list[dict] = []
    last_id = 0
    exhausted = True
    for page in range(1, 6):
        items = _require_list(api.call(
            "GET", f"/issues/{issue}/comments?per_page=100&page={page}",
        ), "ledger_comments_invalid")
        for item in items:
            if not isinstance(item, dict):
                raise Refused("ledger_comment_malformed")
            ident = item.get("id")
            if not isinstance(ident, int) or isinstance(ident, bool) or ident <= last_id:
                raise Refused("ledger_comment_order_invalid")
            last_id = ident
            author = item.get("user")
            if not isinstance(author, dict) or author.get("login") not in publishers:
                continue
            body = item.get("body")
            if not isinstance(body, str) or MARKER not in body:
                continue
            if item.get("updated_at") != item.get("created_at"):
                raise Refused("trusted_ledger_event_edited")
            match = EVENT.search(body)
            if not match:
                raise Refused("trusted_ledger_event_malformed")
            try:
                event = json.loads(match.group(1))
            except ValueError:
                raise Refused("trusted_ledger_event_malformed") from None
            if (not isinstance(event, dict) or event.get("version") != 2
                    or not isinstance(event.get("payload"), dict)):
                raise Refused("trusted_ledger_event_version_invalid")
            events.append(event)
        if len(items) < 100:
            exhausted = False
            break
    if exhausted or len(events) > MAX_EVENTS:
        raise Refused("ledger_history_unbounded")
    matching = [
        event for event in events
        if event.get("type") == "MERGED"
        and event["payload"].get("pr") == number
        and event["payload"].get("work_unit") == wu
        and event["payload"].get("approved_head") == repaired
        and event["payload"].get("approved_base") == base
        and event["payload"].get("merge_sha") == merge_sha
    ]
    if len(matching) != 1:
        raise Refused("durable_exact_head_merge_event_missing_or_ambiguous")
    return issue


def _native_review(repo: str, pr: int, review_id: int,
                   head: str, base: str) -> dict:
    """Use base-trusted actor mapping and author exclusions from merge kernel."""
    from platform_identity import (
        pull_request_material_author_actor_ids, review_platform_identity,
        require_authority,
    )
    actors, errors = pull_request_material_author_actor_ids(
        repo, pr, head, base,
    )
    if actors is None or errors:
        raise Refused("native_material_author_identity_unverified")
    identity, errors = review_platform_identity(
        repo, pr, review_id, head, base, allowed_states={"APPROVED"},
    )
    if identity is None or errors:
        raise Refused("native_platform_reviewer_unverified")
    eligible, reasons = require_authority(identity, "code_review", actors)
    if not eligible or reasons:
        raise Refused("native_independent_reviewer_unverified")
    return identity


def _native_merged_event(repo: str, pr: int, wu: str, base: str,
                         head: str, merge_sha: str) -> None:
    """Require canonical ledger admission + verified MERGED replay, not JSON."""
    import ledger_lib
    from lease_lifecycle import coordination_view

    if ledger_lib._repository() != repo or not ledger_lib.ledger_enabled():
        raise Refused("native_ledger_repository_or_activation_mismatch")
    try:
        events = ledger_lib.list_events()
        matching = [
            event for event in events
            if event.get("type") == "MERGED"
            and isinstance(event.get("payload"), dict)
            and event["payload"].get("pr") == pr
            and event["payload"].get("work_unit") == wu
            and event["payload"].get("approved_base") == base
            and event["payload"].get("approved_head") == head
            and event["payload"].get("merge_sha") == merge_sha
        ]
        if len(matching) != 1:
            raise Refused("native_durable_merged_event_missing")
        context, error = ledger_lib._verify_merged_event(matching[0])
        if context is None or error:
            raise Refused("native_merged_event_failed_platform_proof")
        view = coordination_view()
    except Refused:
        raise
    except Exception:
        raise Refused("native_merged_ledger_replay_unavailable") from None
    if (not isinstance(view, dict)
            or wu not in set(view.get("verified_merged_work_units", []))):
        raise Refused("native_durable_merge_not_verified")


def _utc_platform(value: Any) -> dt.datetime:
    """Reject naive, malformed, or unanchored GitHub platform timestamps."""
    if not isinstance(value, str) or not value:
        raise Refused("repair_platform_timestamp_missing")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise Refused("repair_platform_timestamp_invalid") from None
    if parsed.tzinfo is None:
        raise Refused("repair_platform_timestamp_unanchored")
    return parsed.astimezone(dt.timezone.utc)


def _historical_repair_lease(*, repo: str, number: int, wu: str,
                             actor: str, branch: str, base: str,
                             initial: str, lease_id: str,
                             started: dt.datetime,
                             completed: dt.datetime) -> None:
    """Replay actual owner-published ledger at BOTH GitHub job timestamps.

    A current or later MERGED event does not prove that a lease existed when
    the worker started or when it pushed; historical replay uses ONLY events
    published by each cutoff, including transfers, expiry, and reaping.
    """
    import ledger_lib
    from lease_lifecycle import derive_lifecycle

    try:
        if ledger_lib._repository() != repo or not ledger_lib.ledger_enabled():
            raise Refused("repair_native_ledger_unavailable")
        events = ledger_lib.list_events()
        stamped = []
        for event in events:
            if not isinstance(event, dict):
                raise Refused("repair_native_ledger_malformed")
            stamped.append((_utc_platform(event.get("github_created_at")), event))
        for instant in (started, completed):
            historical = [
                event for when, event in stamped if when <= instant
            ]
            view = derive_lifecycle(
                historical, number, now=instant, durable=True,
            )
            if (not isinstance(view, dict)
                    or view.get("lifecycle_rejected_claims")
                    or view.get("integrity_conflicts")
                    or view.get("conflicts")
                    or view.get("rejected_claims")):
                raise Refused("repair_historical_ledger_rejected")
            active = view.get("active_leases")
            if not isinstance(active, list) or len(active) != 1:
                raise Refused("repair_historical_lease_missing")
            lease = active[0]
            admission = (lease.get("admission_snapshot")
                         if isinstance(lease, dict) else None)
            if (not isinstance(admission, dict)
                    or lease.get("id") != lease_id
                    or lease.get("role") != "implementation"
                    or lease.get("status") != "active"
                    or lease.get("pr") != number
                    or lease.get("work_unit") != wu
                    or lease.get("actor") != actor
                    or lease.get("branch") != branch
                    or admission.get("trusted_ref") != base
                    or initial not in {
                        lease.get("start_head"), lease.get("last_progress_head")
                    }):
                raise Refused("repair_historical_lease_mismatch")
    except Refused:
        raise
    except Exception:
        raise Refused("repair_historical_ledger_unavailable") from None


def _repair_run_evidence(api: GitHub, entry: dict, *, repo: str,
                         number: int, wu: str, actor: str, base: str,
                         initial: str, repaired: str,
                         failed_id: int) -> dict:
    """Verify platform-bound repair workflow/job/log plus historical lease."""
    run_id = _positive_int(entry.get("repair_run_id"),
                           "repair_run_id_required")
    attempt = _positive_int(entry.get("repair_run_attempt"),
                            "repair_run_attempt_required")
    run = _require_object(
        api.call("GET", f"/actions/runs/{run_id}"),
        "repair_run_unavailable",
    )
    owner = _require_object(run.get("repository"),
                            "repair_run_repository_unavailable")
    if (run.get("event") != "workflow_dispatch"
            or run.get("path") != REPAIR_PATH
            or run.get("head_sha") != base
            or run.get("status") != "completed"
            or run.get("conclusion") != "success"
            or run.get("run_attempt") != attempt
            or owner.get("full_name") != repo):
        raise Refused("repair_workflow_identity_mismatch")
    for path, expected in (
        (REPAIR_PATH, REPAIR_WORKFLOW_BLOB),
        ("scripts/l2_fixture_repair.py", REPAIR_SCRIPT_BLOB),
    ):
        _, document = _content(api, path, base)
        if document.get("sha") != expected:
            raise Refused("repair_base_trusted_worker_drift")
    listing = _require_object(api.call(
        "GET", f"/actions/runs/{run_id}/jobs?per_page=100",
    ), "repair_jobs_unavailable")
    jobs = _require_list(listing.get("jobs"), "repair_jobs_unavailable")
    if len(jobs) >= 100:
        raise Refused("repair_jobs_truncated")
    matching = [
        job for job in jobs if isinstance(job, dict)
        and job.get("name") == REPAIR_JOB
        and job.get("status") == "completed"
        and job.get("conclusion") == "success"
        and job.get("run_id") == run_id
        and job.get("run_attempt") == attempt
    ]
    if len(matching) != 1:
        raise Refused("repair_job_identity_mismatch")
    job = matching[0]
    steps = _require_list(job.get("steps"), "repair_steps_unavailable")
    if sum(
        isinstance(step, dict)
        and step.get("name") == REPAIR_STEP
        and step.get("conclusion") == "success"
        for step in steps
    ) != 1:
        raise Refused("repair_job_step_unverified")
    started = _utc_platform(job.get("started_at"))
    completed = _utc_platform(job.get("completed_at"))
    if not started < completed:
        raise Refused("repair_job_time_invalid")
    job_id = _positive_int(job.get("id"), "repair_job_id_invalid")
    lines = [
        line.split(EVIDENCE_PREFIX, 1)[1].strip()
        for line in _job_log(api, job_id).splitlines()
        if EVIDENCE_PREFIX in line
    ]
    if len(lines) != 1:
        raise Refused("repair_job_evidence_missing_or_ambiguous")
    try:
        evidence = json.loads(lines[0])
    except ValueError:
        raise Refused("repair_job_evidence_invalid") from None
    if not isinstance(evidence, dict):
        raise Refused("repair_job_evidence_invalid")
    expected = {
        "status": "L2_REPAIR_COMMITTED",
        "repository": repo, "work_unit": wu, "actor": actor,
        "pr": number, "initial": initial, "repaired": repaired,
        "base": base, "failed_ci_run_id": failed_id,
        "already_applied": False,
        "run_id": run_id, "run_attempt": attempt,
    }
    if any(evidence.get(key) != value for key, value in expected.items()):
        raise Refused("repair_job_evidence_identity_mismatch")
    lease_id = evidence.get("lease_id")
    if not isinstance(lease_id, str) or not lease_id:
        raise Refused("repair_job_lease_id_missing")
    _historical_repair_lease(
        repo=repo, number=number, wu=wu, actor=actor,
        branch=branch_for(wu), base=base, initial=initial,
        lease_id=lease_id, started=started, completed=completed,
    )
    return {
        "repair_run_id": run_id, "repair_job_id": job_id,
        "repair_run_attempt": attempt, "lease_id": lease_id,
    }


def verify_l2(entry: dict[str, Any], token: str,
              factory: Callable[[str, str], GitHub] = GitHub) -> dict:
    """Observe an actual L2 pilot; never infer capability from manifest claims."""
    if not isinstance(entry, dict):
        raise Refused("l2_manifest_invalid")
    repo, wu, actor = (_string(entry, key) for key in
                       ("repository", "wu", "actor"))
    if not REPO.fullmatch(repo) or not re.fullmatch(r"WU[A-Za-z0-9._-]{1,58}", wu):
        raise Refused("l2_pilot_identity_invalid")
    base, initial, repaired = (
        _sha(entry, key) for key in
        ("base_sha", "initial_head", "repaired_head")
    )
    if len({base, initial, repaired}) != 3:
        raise Refused("l2_head_progress_missing")
    number = _positive_int(entry.get("pr_number"), "l2_pr_number_invalid")
    failed_id = _positive_int(entry.get("failed_run_id"), "failed_run_invalid")
    passed_id = _positive_int(entry.get("passed_run_id"), "passed_run_invalid")
    review_id = _positive_int(entry.get("review_id"), "review_id_invalid")
    api = factory(repo, token)
    meta = _require_object(api.call("GET", "/"), "l2_repo_invalid")
    if (meta.get("full_name") != repo or meta.get("private") is not False
            or meta.get("visibility") != "public"):
        raise Refused("l2_requires_public_disposable_project")
    pr = _require_object(api.call("GET", f"/pulls/{number}"), "l2_pr_invalid")
    head = _require_object(pr.get("head"), "l2_pr_identity_invalid")
    target = _require_object(pr.get("base"), "l2_pr_identity_invalid")
    head_repo = _require_object(head.get("repo"), "l2_pr_identity_invalid")
    base_repo = _require_object(target.get("repo"), "l2_pr_identity_invalid")
    if (pr.get("number") != number or not pr.get("merged_at")
            or not isinstance(pr.get("merge_commit_sha"), str)
            or not SHA.fullmatch(pr["merge_commit_sha"])
            or head.get("sha") != repaired or target.get("sha") != base
            or head.get("ref") != branch_for(wu)
            or target.get("ref") != meta.get("default_branch")
            or head_repo.get("full_name") != repo
            or base_repo.get("full_name") != repo):
        raise Refused("l2_same_canonical_pr_not_merged_or_drifted")
    path = f"docs/onecompany-fixture/{wu}.md"
    comparison = _require_object(
        api.call("GET", f"/compare/{base}...{repaired}"),
        "l2_comparison_invalid",
    )
    files = _require_list(comparison.get("files"), "l2_comparison_invalid")
    commits = _require_list(comparison.get("commits"), "l2_comparison_invalid")
    if (comparison.get("status") != "ahead" or len(files) != 1
            or not isinstance(files[0], dict)
            or files[0].get("filename") != path
            or files[0].get("status") != "added"
            or len(commits) != 2
            or [c.get("sha") for c in commits
                if isinstance(c, dict)] != [initial, repaired]):
        raise Refused("l2_not_one_repair_on_one_fixture_pr")
    repair_commit = _require_object(api.call(
        "GET", "/git/commits/" + repaired,
    ), "l2_repair_commit_invalid")
    parents = repair_commit.get("parents")
    if (not isinstance(parents, list) or len(parents) != 1
            or not isinstance(parents[0], dict)
            or parents[0].get("sha") != initial):
        raise Refused("l2_repair_not_direct_descendant")
    first_content, _ = _content(api, path, initial)
    second_content, _ = _content(api, path, repaired)
    if (first_content != fixture_body(repo, wu, actor, base)
            or second_content != first_content + REPAIR_LINE):
        raise Refused("l2_not_exact_bounded_ci_repair")
    _, ci = _content(api, CI_PATH, base)
    if ci.get("sha") != CI_BLOB:
        raise Refused("l2_ci_workflow_not_base_trusted")
    _run(api, failed_id, initial, "failure")
    _run(api, passed_id, repaired, "success")
    jobs = _require_object(api.call(
        "GET", f"/actions/runs/{failed_id}/jobs?per_page=100",
    ), "l2_failed_jobs_invalid")
    all_jobs = _require_list(jobs.get("jobs"), "l2_failed_jobs_invalid")
    if len(all_jobs) >= 100:
        raise Refused("l2_failed_jobs_truncated")
    failed_jobs = [
        job for job in all_jobs if isinstance(job, dict)
        and job.get("name") == "validate-fixture"
        and job.get("conclusion") == "failure"
    ]
    if len(failed_jobs) != 1:
        raise Refused("l2_intentional_fixture_failure_not_proven")
    failed_job = failed_jobs[0]
    steps = _require_list(failed_job.get("steps"),
                          "l2_failed_steps_invalid")
    if not any(
        isinstance(step, dict)
        and step.get("name") == "Validate one bounded repaired fixture"
        and step.get("conclusion") == "failure"
        for step in steps
    ):
        raise Refused("l2_intentional_fixture_failure_not_proven")
    job_id = _positive_int(failed_job.get("id"),
                           "l2_failed_job_id_invalid")
    if sum(
        line.strip().endswith(FAILURE_MARKER)
        for line in _job_log(api, job_id).splitlines()
    ) != 1:
        raise Refused("l2_intentional_fixture_failure_not_proven")
    _check(api, initial, failed_id, "failure")
    _check(api, repaired, passed_id, "success")
    repair_proof = _repair_run_evidence(
        api, entry, repo=repo, number=number, wu=wu, actor=actor,
        base=base, initial=initial, repaired=repaired,
        failed_id=failed_id,
    )
    reviews = _require_list(api.call(
        "GET", f"/pulls/{number}/reviews?per_page=100",
    ), "l2_reviews_invalid")
    if len(reviews) >= 100:
        raise Refused("l2_reviews_truncated")
    matches = [rev for rev in reviews
               if isinstance(rev, dict) and rev.get("id") == review_id
               and rev.get("commit_id") == repaired
               and rev.get("state") == "APPROVED"]
    if len(matches) != 1:
        raise Refused("independent_exact_head_review_missing")
    reviewer = _require_object(matches[0].get("user"),
                               "reviewer_identity_invalid").get("login")
    if not isinstance(reviewer, str) or not reviewer:
        raise Refused("reviewer_identity_invalid")
    authors = set()
    for sha in (initial, repaired):
        commit = _require_object(api.call(
            "GET", "/commits/" + sha,
        ), "commit_author_invalid")
        account = _require_object(commit.get("author"), "commit_author_invalid")
        login = account.get("login")
        if not isinstance(login, str) or not login:
            raise Refused("material_author_account_unverified")
        authors.add(login)
    if reviewer in authors:
        raise Refused("self_review_not_independent")
    reviewer_identity = _native_review(
        repo, number, review_id, repaired, base,
    )
    if reviewer_identity.get("login") != reviewer:
        raise Refused("native_review_login_mismatch")
    merge_sha = pr["merge_commit_sha"]
    issue = _owner_merged_event(
        api, base, number=number, wu=wu, repaired=repaired,
        merge_sha=merge_sha,
    )
    _native_merged_event(repo, number, wu, base, repaired, merge_sha)
    return {
        "status": "L2_LIVE_SAME_PR_FLOW_OBSERVED",
        "authority": "read_only_qualification_report",
        "repository": repo, "pr": number, "work_unit": wu,
        "initial_head": initial, "repaired_head": repaired,
        "failed_run_id": failed_id, "passed_run_id": passed_id,
        **repair_proof,
        "independent_reviewer_login": reviewer,
        "independent_reviewer_actor": reviewer_identity["actor_id"],
        "merged_commit": merge_sha, "ledger_issue": issue,
        "note": "Observed GitHub and trusted ledger records; not a merge grant.",
    }


def verify_worker_attribution(entry: dict, token: str,
                              factory: Callable[[str, str], GitHub] = GitHub) -> dict:
    """Distinguish bot-attributed commits from verified App-token write access."""
    if not isinstance(entry, dict):
        raise Refused("worker_manifest_invalid")
    repo = _string(entry, "repository")
    if repo != "NTinkicht/OneCompany":
        raise Refused("grok_adapter_not_approved_for_foreign_repo")
    number = _positive_int(entry.get("pr_number"), "worker_pr_invalid")
    head = _sha(entry, "head_sha")
    api = factory(repo, token)
    pr = _require_object(api.call("GET", f"/pulls/{number}"), "worker_pr_invalid")
    pr_head = _require_object(pr.get("head"), "worker_pr_head_invalid")
    pr_repo = _require_object(pr_head.get("repo"), "worker_pr_head_invalid")
    if (pr_head.get("sha") != head
            or pr_repo.get("full_name") != repo):
        raise Refused("worker_pr_head_drift")
    commit = _require_object(api.call("GET", "/commits/" + head),
                             "worker_commit_invalid")
    author = _require_object(commit.get("author"), "worker_author_invalid")
    if author.get("login") != "onecompany-grok-worker[bot]":
        raise Refused("grok_bot_commit_not_observed")
    return {
        "status": "BOT_COMMIT_ATTRIBUTION_OBSERVED",
        "repository": repo, "pr": number, "head": head,
        "authenticated_app_write_verified": False,
        "unattended_writer_verified": False,
        "independent_reviewer_verified": False,
        "note": "A Git commit author association cannot prove the token principal. "
                "Confirm a real GitHub App-authenticated write trace separately.",
    }


def verify_campaign(manifest: dict, token: str) -> dict:
    """Report live proofs by phase; block full completion until all are real."""
    if not isinstance(manifest, dict):
        raise Refused("campaign_manifest_invalid")
    pilots = manifest.get("a4_pilots")
    if not isinstance(pilots, list) or len(pilots) != 2:
        raise Refused("two_a4_pilots_required")
    a4 = verify_pair(pilots, token)
    worker = verify_worker_attribution(manifest.get("grok_worker"), token)
    l2 = verify_l2(manifest.get("l2_pilot"), token)
    # A bot-authored commit alone NEVER proves App-token write identity.
    return {
        "status": "P1_P3_EVIDENCE_OBSERVED_P2_AUTHENTICATED_WRITE_PENDING",
        "a4": a4, "grok_worker": worker, "l2": l2,
        "source_autonomy_promoted": False,
        "unattended_multi_agent_workforce_verified": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    token = os.getenv("GH_TOKEN", "")
    if not token:
        print("P123_QUALIFY_REFUSED:missing_read_only_token", file=sys.stderr)
        return 2
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        outcome = verify_campaign(manifest, token)
    except (Refused, OSError, UnicodeError, ValueError) as exc:
        reason = str(exc) if isinstance(exc, Refused) else "manifest_invalid"
        print("P123_QUALIFY_REFUSED:" + reason, file=sys.stderr)
        return 2
    print(json.dumps(outcome, sort_keys=True, indent=2))
    # An observed GitHub author login never qualifies P2 token-bound writes.
    # Return a nonzero result so automation cannot interpret this partial
    # campaign evidence as a completed P1–P3 qualification.
    return 2


if __name__ == "__main__":
    sys.exit(main())
