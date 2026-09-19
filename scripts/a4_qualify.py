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
