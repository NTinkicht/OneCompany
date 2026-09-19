"""Read-side authoritative WU/lease inspection for a future GitHub App writer.

No source files, GitHub branches or issues are mutated here. This *cannot* be
given model-supplied PR/base/lease documents: every fact is fetched from the
allowlisted repository with an installation token, bound to the PR base, and
verified before calling the pure write policy. No writer MCP tool is exported.
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import re
from typing import Any

from github_app import AdapterRefused, AppClient
from write_policy import WriteRequest, WriteRefused, verify_write_contract

_MARKER = "<!-- onecompany-ledger-v1 -->"
_EVENT = re.compile(
    r"<!-- onecompany-ledger-v1 -->\s*```json\s*(\{.*?\})\s*```",
    re.DOTALL,
)
_POLICY = {
    "queue": ".onecompany/queue.json",
    "planning": ".onecompany/planning.json",
    "actors": ".onecompany/actors.json",
    "readiness": ".onecompany/readiness.json",
    "budget": ".onecompany/budget.json",
}
_MAX_PAGES = 10
_PER_PAGE = 50


def _utc(value: str) -> dt.datetime:
    try:
        date = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if date.tzinfo is None:
            raise ValueError("naive")
        return date.astimezone(dt.timezone.utc)
    except (ValueError, AttributeError, TypeError):
        raise WriteRefused("ledger_timestamp_invalid") from None


def parse_trusted_events(comments: list[dict], publishers: set[str]) -> list[dict]:
    """Accept only unedited v2 owner-published ledger events, ordered by id."""
    if not publishers or not comments or len(comments) > _MAX_PAGES * _PER_PAGE:
        raise WriteRefused("ledger_incomplete")
    events: list[dict] = []
    seen: set[str] = set()
    previous_id = 0
    for c in comments:
        if not isinstance(c, dict) or not isinstance(c.get("id"), int):
            raise WriteRefused("ledger_comment_invalid")
        if c["id"] <= previous_id:
            raise WriteRefused("ledger_order_invalid")
        previous_id = c["id"]
        if (c.get("user") or {}).get("login") not in publishers:
            continue
        text = c.get("body")
        if not isinstance(text, str) or _MARKER not in text:
            continue
        if c.get("updated_at") != c.get("created_at"):
            raise WriteRefused("ledger_edited_event")
        matched = _EVENT.search(text)
        if not matched:
            raise WriteRefused("ledger_malformed_trusted_event")
        try:
            event = json.loads(matched.group(1))
        except json.JSONDecodeError:
            raise WriteRefused("ledger_malformed_trusted_event") from None
        if (not isinstance(event, dict) or event.get("version") != 2
                or not isinstance(event.get("event_id"), str)
                or not event.get("event_id")
                or not isinstance(event.get("actor"), str)
                or not isinstance(event.get("payload"), dict)
                or not isinstance(event.get("type"), str)):
            raise WriteRefused("ledger_event_schema_invalid")
        if event["event_id"] in seen:
            raise WriteRefused("ledger_duplicate_event_id")
        seen.add(event["event_id"])
        timestamp = _utc(c["created_at"])
        claimed = event.get("timestamp")
        if claimed is not None and abs((_utc(claimed) - timestamp).total_seconds()) > 300:
            raise WriteRefused("ledger_timestamp_not_platform_bound")
        events.append({
            "id": event["event_id"], "type": event["type"],
            "actor": event["actor"], "payload": event["payload"],
            "created_at": timestamp, "comment_id": c["id"],
        })
    return events


def active_implementation_lease(
    events: list[dict], *, lease_id: str, work_unit: str, pr_number: int,
    now: dt.datetime, ttl_seconds: int,
) -> dict:
    """Conservative lifecycle subset: fail closed on ambiguous renew/transfer."""
    if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool) or not 0 < ttl_seconds <= 14400:
        raise WriteRefused("ledger_ttl_unverified")
    active: dict[str, dict] = {}
    for event in events:
        kind, payload = event["type"], event["payload"]
        if kind == "ROLE_LEASE_ASSIGNED":
            lid = payload.get("lease_id")
            if not isinstance(lid, str) or not lid or lid in active:
                raise WriteRefused("ledger_lease_conflict")
            active[lid] = {
                "id": lid, "actor": event["actor"],
                "role": payload.get("role", "implementation"),
                "work_unit": payload.get("work_unit"),
                "pr": payload.get("pr"),
                "branch": payload.get("branch"),
                "start_head": payload.get("start_head"),
                "admission_snapshot": payload.get("admission_snapshot"),
                "planning_snapshot": payload.get("planning_snapshot"),
                "status": "active",
                "expires_at": (
                    event["created_at"] + dt.timedelta(seconds=ttl_seconds)
                ).isoformat(),
            }
        elif kind == "ROLE_LEASE_TRANSFERRED":
            old = payload.get("old_lease_id")
            lid = payload.get("new_lease_id")
            if old not in active or not isinstance(lid, str) or not lid or lid in active:
                raise WriteRefused("ledger_transfer_ambiguous")
            del active[old]
            active[lid] = {
                "id": lid, "actor": event["actor"],
                "role": payload.get("role", "implementation"),
                "work_unit": payload.get("work_unit"),
                "pr": payload.get("pr"),
                "branch": payload.get("branch"),
                "start_head": payload.get("start_head"),
                "admission_snapshot": payload.get("admission_snapshot"),
                "planning_snapshot": payload.get("planning_snapshot"),
                "status": "active",
                "expires_at": (
                    event["created_at"] + dt.timedelta(seconds=ttl_seconds)
                ).isoformat(),
            }
        elif kind in {"ROLE_LEASE_RELEASED", "ROLE_LEASE_REAPED"}:
            lid = payload.get("lease_id")
            if lid in active:
                del active[lid]
        elif kind == "ROLE_LEASE_RENEWED":
            if payload.get("lease_id") == lease_id:
                # A renewal requires independent platform proof of PR-head
                # progress; this conservative reader does not implement it.
                raise WriteRefused("ledger_renewal_requires_full_kernel")
        elif kind == "MERGED" and payload.get("work_unit") == work_unit:
            raise WriteRefused("work_unit_already_merged")
    matching = [
        item for item in active.values()
        if item.get("work_unit") == work_unit or item.get("pr") == pr_number
    ]
    if len(matching) != 1 or matching[0]["id"] != lease_id:
        raise WriteRefused("active_canonical_lease_not_unique")
    if _utc(matching[0]["expires_at"]) <= now.astimezone(dt.timezone.utc):
        raise WriteRefused("active_lease_expired")
    return matching[0]


class VerifiedWriterReadSide:
    """No mutation API; useful only after full OneCompany kernel integration."""

    def __init__(self, client: AppClient):
        self.client = client
        self.settings = client.settings

    def _base_file(self, token: str, sha: str, path: str) -> tuple[dict, str]:
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise WriteRefused("untrusted_base_sha")
        result = self.client._stage_call(
            "trusted_base", "GET",
            f"/repos/{self.settings.repository}/contents/{path}?ref={sha}",
            token,
        )
        if (not isinstance(result, dict) or result.get("type") != "file"
                or not isinstance(result.get("sha"), str)
                or result.get("encoding") != "base64"):
            raise WriteRefused("trusted_base_document_unavailable")
        try:
            content = base64.b64decode(
                re.sub(r"\s+", "", result["content"]), validate=True,
            )
            if len(content) > 128_000:
                raise ValueError("large")
            doc = json.loads(content)
            if not isinstance(doc, dict):
                raise ValueError("not_object")
            return doc, result["sha"]
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise WriteRefused("trusted_base_document_invalid") from None

    def _events(self, token: str, issue: int, publishers: set[str]) -> list[dict]:
        comments: list[dict] = []
        for page in range(1, _MAX_PAGES + 1):
            result = self.client._stage_call(
                "durable_ledger", "GET",
                f"/repos/{self.settings.repository}/issues/{issue}/comments?"
                f"per_page={_PER_PAGE}&page={page}", token,
            )
            if not isinstance(result, list):
                raise WriteRefused("ledger_page_invalid")
            comments.extend(result)
            if len(result) < _PER_PAGE:
                return parse_trusted_events(comments, publishers)
        # Never silently drop later comments; missing release/transfer is fatal.
        raise WriteRefused("ledger_pagination_limit")

    def inspect(self, request: WriteRequest, now: dt.datetime,
                feature_enabled: bool = False) -> dict:
        if not feature_enabled:
            raise WriteRefused("writer_disabled")
        if self.settings.repository != "NTinkicht/OneCompany":
            raise WriteRefused("foreign_repository")
        token, slug, _ = self.client._installation()
        if slug != "onecompany-grok-worker":
            raise WriteRefused("unexpected_app_principal")
        repo = self.client._stage_call(
            "repository", "GET", f"/repos/{self.settings.repository}", token,
        )
        if not isinstance(repo, dict) or repo.get("default_branch") != "main":
            raise WriteRefused("default_branch_unverified")
        main_ref = self.client._stage_call(
            "default_branch", "GET",
            f"/repos/{self.settings.repository}/git/ref/heads/main", token,
        )
        main_sha = (main_ref.get("object") or {}).get("sha") if isinstance(main_ref, dict) else None
        if not isinstance(main_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", main_sha):
            raise WriteRefused("default_branch_sha_unverified")
        pr = self.client._stage_call(
            "live_pr", "GET",
            f"/repos/{self.settings.repository}/pulls/{request.pr_number}",
            token,
        )
        if (not isinstance(pr, dict) or
                (pr.get("base") or {}).get("sha") != main_sha):
            raise WriteRefused("live_pr_base_stale")
        config, _ = self._base_file(token, main_sha, ".onecompany/config.json")
        ledger, _ = self._base_file(token, main_sha, ".onecompany/ledger.json")
        if ledger.get("enabled") is not True or ledger.get("event_format_version") != 2:
            raise WriteRefused("durable_ledger_not_active")
        issue = ledger.get("issue_number")
        publishers = ledger.get("trusted_publisher_logins")
        if (not isinstance(issue, int) or issue < 1
                or not isinstance(publishers, list) or publishers != ["NTinkicht"]):
            raise WriteRefused("ledger_publisher_policy_unverified")
        docs: dict[str, dict] = {}
        blob_hashes: dict[str, str] = {}
        for name, path in _POLICY.items():
            docs[name], blob_hashes[name] = self._base_file(
                token, main_sha, path,
            )
        events = self._events(token, issue, set(publishers))
        lifecycle = ledger.get("lease_lifecycle")
        if not isinstance(lifecycle, dict) or lifecycle.get("implicit_expiry_revokes_authority") is not True:
            raise WriteRefused("lease_lifecycle_unverified")
        lease = active_implementation_lease(
            events, lease_id=request.lease_id, work_unit=request.work_unit,
            pr_number=request.pr_number, now=now,
            ttl_seconds=lifecycle.get("ttl_seconds"),
        )
        admission = lease.get("admission_snapshot")
        if (not isinstance(admission, dict)
                or admission.get("policy_blobs") != blob_hashes):
            raise WriteRefused("lease_base_policy_blobs_unverified")
        work = next(
            (item for item in docs["queue"].get("work_units", [])
             if item.get("id") == request.work_unit), None,
        )
        actor = next(
            (a for a in docs["actors"].get("actors", [])
             if a.get("id") == request.actor), None,
        )
        ready = next(
            (a for a in docs["readiness"].get("actors", [])
             if a.get("actor_id") == request.actor), None,
        )
        if (not isinstance(actor, dict) or actor.get("enabled") is not True
                or actor.get("configured") is not True
                or not isinstance(ready, dict)
                or ready.get("repository_access", {}).get("write") is not True
                or "implementation" not in ready.get("verified_capabilities", [])
                or ready.get("capacity", {}).get("implementation_streams", 0) < 1):
            raise WriteRefused("actor_writer_readiness_unverified")
        result = verify_write_contract(
            request=request, lease=lease, work_item=work, pr=pr,
            main_sha=main_sha, config=config, now=now,
            feature_enabled=feature_enabled, independently_verified_ledger=True,
            independently_verified_base=True, independently_verified_app=True,
        )
        return {
            **result, "note": (
                "Read-only preflight, not a credential grant or commit. "
                "Full OneCompany admission and live ref CAS remain mandatory."
            ),
        }
