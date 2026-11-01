"""Live reconcile runner chaining bundle capture, snapshot and verdict (#397).

OC-P0-01: ``capture_bundle`` (#395), ``snapshot_from_bundle`` (#387) and ``build_report``
exist but nothing chained them, so a hand-wired runner could skip the main-movement
refusal, feed an unvalidated bundle to the checks, or read a capture failure as "no
findings".

This pure module runs them in order with an injected transport. Any capture, bundle or
snapshot failure becomes one ``LiveReconciliationRefused`` that names the step only,
never a response body; refusal is never a verdict. The verdict from ``build_report`` is
returned unchanged. ``now`` must be timezone-aware and is supplied by the caller; nothing
here performs a request, reads a token or reads the clock.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Any, Mapping, Sequence

from github_bundle_capture import capture_bundle
from github_bundle_snapshot import InvalidBundle, snapshot_from_bundle
from github_page_capture import DEFAULT_MAX_PAGES, CaptureError, Fetch
from live_reconciliation_report import DEFAULT_MAX_AGE_SECONDS, InvalidSnapshot, build_report


class LiveReconciliationRefused(ValueError):
    """The live state could not be captured or validated; no verdict exists."""


def reconcile_live(
    fetch: Fetch, repo: str, pulls: Sequence[Mapping[str, Any]], *, now: dt.datetime,
    observed_at: str, main_sha: str, active_lease_issue_ids: Sequence[int],
    retired_pilot_issue_ids: Sequence[int], write_attempts: Sequence[Any],
    trusted_reviewers: Sequence[str], app_slugs: Mapping[str, str],
    max_pages: int = DEFAULT_MAX_PAGES, max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
) -> dict[str, Any]:
    """Return the ``build_report`` verdict for one live capture, or raise."""
    if type(now) is not dt.datetime or now.tzinfo is None or now.utcoffset() is None:
        raise LiveReconciliationRefused("invalid now")
    try:
        bundle = capture_bundle(
            fetch, repo, pulls, observed_at=observed_at, main_sha=main_sha,
            active_lease_issue_ids=active_lease_issue_ids,
            retired_pilot_issue_ids=retired_pilot_issue_ids, write_attempts=write_attempts,
            trusted_reviewers=trusted_reviewers, app_slugs=app_slugs, max_pages=max_pages)
    except CaptureError as exc:
        raise LiveReconciliationRefused(f"capture refused: {exc}") from None
    try:
        snapshot = snapshot_from_bundle(bundle)
    except InvalidBundle as exc:
        raise LiveReconciliationRefused(f"bundle refused: {exc}") from None
    try:
        return build_report(json.loads(json.dumps(snapshot)), now, max_age_seconds)
    except (InvalidSnapshot, TypeError, ValueError) as exc:
        raise LiveReconciliationRefused(f"snapshot refused: {exc}") from None
