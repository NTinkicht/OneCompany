"""Durable GitHub Team Room ledger helpers for distributed OneCompany runs."""
from __future__ import annotations

import datetime as dt
import json
import re
import uuid
from typing import Any

from capacity_lib import implementation_availability
from onecompany_lib import CONTROL, command_exists, github_repo_from_config, load_json, run
from planning_lib import implementation_admission_violations

MARKER = "<!-- onecompany-ledger-v1 -->"
EVENT_RE = re.compile(r"<!-- onecompany-ledger-v1 -->\s*```json\s*(\{.*?\})\s*```", re.DOTALL)
ADMISSION_SCHEMA = "onecompany-lease-admission-v1"
LEASE_EVENT_TYPES = {"ROLE_LEASE_ASSIGNED", "ROLE_LEASE_TRANSFERRED"}


def ledger_config() -> dict[str, Any]:
    return load_json(CONTROL / "ledger.json")


def ledger_enabled() -> bool:
    return bool(ledger_config().get("enabled"))


def _repo_and_issue() -> tuple[str, int]:
    config = load_json(CONTROL / "config.json")
    ledger = ledger_config()
    repo = github_repo_from_config(config)
    issue = ledger.get("issue_number")
    if not repo:
        raise RuntimeError("config.project.repository must be owner/name")
    if not isinstance(issue, int) or issue <= 0:
        raise RuntimeError("ledger.issue_number must be configured")
    return repo, issue


def _trusted_publishers() -> set[str]:
    return set(ledger_config().get("trusted_publisher_logins", []))


def _gh_json(args: list[str]) -> Any:
    if not command_exists("gh"):
        raise RuntimeError("gh CLI is required for durable ledger access")
    result = run(["gh", *args])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gh command failed")
    return json.loads(result.stdout)


def _event_version_allowed(ledger: dict[str, Any], version: Any, comment_id: Any) -> bool:
    current = int(ledger.get("event_format_version", 1))
    accepted = {
        int(value)
        for value in ledger.get("accepted_event_versions", [current])
        if isinstance(value, int) or (isinstance(value, str) and value.isdigit())
    }
    if not isinstance(version, int) or version not in accepted:
        return False
    if version == current:
        return True
    if version == 1:
        try:
            return int(comment_id or 0) <= int(ledger.get("legacy_event_max_comment_id", 0) or 0)
        except (TypeError, ValueError):
            return False
    return False


def list_events() -> list[dict[str, Any]]:
    repo, issue = _repo_and_issue()
    ledger = ledger_config()
    trusted = _trusted_publishers()
    if not trusted:
        raise RuntimeError("ledger has no trusted publisher logins")
    accepted_types = set(ledger.get("accepted_event_types", []))
    raw = _gh_json(
        ["api", "--paginate", "--slurp", f"repos/{repo}/issues/{issue}/comments?per_page=100"]
    )
    pages = raw if isinstance(raw, list) else [raw]
    comments: list[dict[str, Any]] = []
    for page in pages:
        if isinstance(page, list):
            comments.extend(item for item in page if isinstance(item, dict))
        elif isinstance(page, dict):
            comments.append(page)

    events: list[dict[str, Any]] = []
    for comment in comments:
        login = ((comment.get("user") or {}).get("login"))
        if login not in trusted:
            continue
        body = comment.get("body") or ""
        if MARKER not in body:
            continue
        match = EVENT_RE.search(body)
        if not match:
            raise RuntimeError(f"malformed trusted ledger event in comment {comment.get('id')}")
        if (
            comment.get("updated_at")
            and comment.get("created_at")
            and comment.get("updated_at") != comment.get("created_at")
        ):
            raise RuntimeError(
                f"trusted ledger event was edited after append in comment {comment.get('id')}"
            )
        try:
            event = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"invalid JSON in trusted ledger comment {comment.get('id')}: {exc}"
            ) from exc
        if not _event_version_allowed(ledger, event.get("version"), comment.get("id")):
            raise RuntimeError(
                f"unsupported or post-cutoff legacy ledger event version in comment {comment.get('id')}"
            )
        if event.get("type") not in accepted_types:
            raise RuntimeError(
                f"unsupported ledger event type in comment {comment.get('id')}: {event.get('type')}"
            )
        if not isinstance(event.get("event_id"), str) or not event.get("event_id"):
            raise RuntimeError(f"trusted ledger event missing event_id in comment {comment.get('id')}")
        if not isinstance(event.get("actor"), str) or not event.get("actor"):
            raise RuntimeError(f"trusted ledger event missing actor in comment {comment.get('id')}")
        if not isinstance(event.get("payload"), dict):
            raise RuntimeError(
                f"trusted ledger event payload must be object in comment {comment.get('id')}"
            )
        event["github_comment_id"] = comment.get("id")
        event["github_comment_url"] = comment.get("html_url")
        event["github_publisher"] = login
        event["github_created_at"] = comment.get("created_at")
        events.append(event)
    events.sort(
        key=lambda item: (
            item.get("github_created_at") or "",
            int(item.get("github_comment_id") or 0),
        )
    )
    return events


def _v2_payload_error(event_type: str, actor: str, payload: dict[str, Any]) -> str | None:
    if event_type not in LEASE_EVENT_TYPES:
        return None
    admission = payload.get("admission_snapshot")
    if not isinstance(admission, dict):
        return "v2 implementation lease event requires admission_snapshot"
    if admission.get("schema") != ADMISSION_SCHEMA:
        return f"unsupported lease admission schema: {admission.get('schema')!r}"
    if admission.get("actor") != actor:
        return "lease admission actor does not match event actor"
    limit = admission.get("actor_limit")
    if not isinstance(limit, int) or limit <= 0:
        return "lease admission actor_limit must be a positive integer"
    dependencies = admission.get("dependencies")
    if not isinstance(dependencies, list) or any(not isinstance(value, str) for value in dependencies):
        return "lease admission dependencies must be a string array"
    if event_type == "ROLE_LEASE_ASSIGNED":
        if admission.get("transfer_source_lease_id") not in {None, ""}:
            return "assignment admission cannot name a transfer source"
    if event_type == "ROLE_LEASE_TRANSFERRED":
        if admission.get("transfer_source_lease_id") != payload.get("old_lease_id"):
            return "transfer admission source does not match old_lease_id"
    return None


def post_event(event_type: str, actor: str, payload: dict[str, Any]) -> dict[str, Any]:
    ledger = ledger_config()
    if not ledger.get("enabled"):
        raise RuntimeError("durable ledger is disabled")
    if event_type not in set(ledger.get("accepted_event_types", [])):
        raise RuntimeError(f"unsupported ledger event type: {event_type}")
    trusted = _trusted_publishers()
    if not trusted:
        raise RuntimeError("ledger requires at least one trusted publisher login")
    version = int(ledger.get("event_format_version", 1))
    if version >= 2:
        payload_error = _v2_payload_error(event_type, actor, payload)
        if payload_error:
            raise RuntimeError(payload_error)
    repo, issue = _repo_and_issue()
    event = {
        "version": version,
        "event_id": str(uuid.uuid4()),
        "type": event_type,
        "actor": actor,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "payload": payload,
    }
    body = (
        f"{MARKER}\n```json\n"
        f"{json.dumps(event, separators=(',', ':'), ensure_ascii=False)}\n```\n"
    )
    posted = _gh_json(
        ["gh", "noop"]
    ) if False else _gh_json(
        ["api", "--method", "POST", f"repos/{repo}/issues/{issue}/comments", "-f", f"body={body}"]
    )
    login = ((posted.get("user") or {}).get("login"))
    if login not in trusted:
        comment_id = posted.get("id")
        if comment_id:
            run(["gh", "api", "--method", "DELETE", f"repos/{repo}/issues/comments/{comment_id}"])
        raise RuntimeError(f"ledger publisher {login!r} is not trusted; event rejected")
    event["github_comment_id"] = posted.get("id")
    event["github_comment_url"] = posted.get("html_url")
    event["github_publisher"] = login
    event["github_created_at"] = posted.get("created_at")
    return event


def _conflict_id(event: dict[str, Any], reason: str) -> str:
    return f"{event.get('event_id') or '<missing>'}:{reason}"


def derive(
    events: list[dict[str, Any]],
    pr: int | None = None,
    *,
    enforce_actor_policy: bool = True,
) -> dict[str, Any]:
    """Replay durable events into the authoritative coordination view.

    Historical admission is replayed under immutable event-order facts. Current
    readiness/access/budget are projected separately and never erase accepted
    lease lineage or material-authorship history.
    """
    active: dict[str, dict[str, Any]] = {}
    authors_by_pr: dict[int, set[str]] = {}
    gates_by_pr: dict[int, dict[str, Any]] = {}
    rejected_claims: list[dict[str, Any]] = []
    open_integrity_conflicts: dict[str, dict[str, Any]] = {}
    resolved_conflict_ids: set[str] = set()
    seen_event_ids: set[str] = set()
    known_implementation_leases: set[str] = set()
    merged_work_units: set[str] = set()

    try:
        ledger_settings = ledger_config()
    except Exception:
        ledger_settings = {}
    legacy_limits = {
        str(actor): int(limit)
        for actor, limit in (ledger_settings.get("legacy_v1_actor_limits") or {}).items()
        if isinstance(limit, int) and limit > 0
    }
    legacy_unknown_limit = int(ledger_settings.get("legacy_v1_unknown_actor_limit", 1) or 1)
    if legacy_unknown_limit <= 0:
        legacy_unknown_limit = 1

    try:
        planning = load_json(CONTROL / "planning.json")
    except Exception:
        planning = {
            "parallel_execution": {
                "enabled": False,
                "max_concurrent_implementation_streams": 1,
                "require_write_scope_for_parallel": True,
                "critical_risk_default": "serialize",
            }
        }

    try:
        readiness_doc = load_json(CONTROL / "readiness.json")
    except Exception:
        readiness_doc = {"actors": []}
    readiness_by_actor = {
        str(item.get("actor_id")): item
        for item in readiness_doc.get("actors", [])
        if isinstance(item, dict) and item.get("actor_id")
    }
    try:
        actors_doc = load_json(CONTROL / "actors.json")
    except Exception:
        actors_doc = {"actors": []}
    actors_by_id = {
        str(item.get("id")): item
        for item in actors_doc.get("actors", [])
        if isinstance(item, dict) and item.get("id")
    }
    try:
        budget_doc = load_json(CONTROL / "budget.json")
    except Exception:
        budget_doc = {}

    def normalize_pr(value: Any) -> int | None:
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
        return None

    def implementations() -> list[dict[str, Any]]:
        return [item for item in active.values() if item.get("role") == "implementation"]

    def snapshot_item(actor_payload: dict[str, Any]) -> dict[str, Any]:
        snapshot = actor_payload.get("planning_snapshot")
        if not isinstance(snapshot, dict):
            snapshot = {}
        return {"id": actor_payload.get("work_unit"), **snapshot}

    def record_integrity_conflict(event: dict[str, Any], reason: str, **details: Any) -> None:
        conflict = {
            "conflict_id": _conflict_id(event, reason),
            "event_id": event.get("event_id"),
            "type": event.get("type"),
            "reason": reason,
            **details,
        }
        open_integrity_conflicts[str(conflict["conflict_id"])] = conflict

    def record_rejected_claim(
        event: dict[str, Any],
        lease_id: str,
        payload: dict[str, Any],
        violations: list[dict[str, Any]],
        **details: Any,
    ) -> None:
        rejected_claims.append(
            {
                "event_id": event.get("event_id"),
                "type": event.get("type"),
                "work_unit": payload.get("work_unit"),
                "rejected_lease_id": lease_id,
                "violations": violations,
                **details,
            }
        )

    def v2_admission(
        event: dict[str, Any], actor: str | None, payload: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str | None]:
        if int(event.get("version") or 1) < 2:
            return None, [], None
        actor_id = str(actor or "")
        error = _v2_payload_error(str(event.get("type") or ""), actor_id, payload)
        if error:
            return None, [], error
        admission = payload["admission_snapshot"]
        planning_snapshot = payload.get("planning_snapshot")
        if not isinstance(planning_snapshot, dict):
            return None, [], "v2 implementation lease requires planning_snapshot"
        expected_dependencies = sorted(
            {str(value) for value in planning_snapshot.get("dependencies", []) if value}
        )
        recorded_dependencies = sorted(set(admission.get("dependencies", [])))
        if recorded_dependencies != expected_dependencies:
            return None, [], "lease admission dependency set differs from immutable planning snapshot"
        violations: list[dict[str, Any]] = []
        if admission.get("actor_eligible") is not True:
            violations.append(
                {
                    "reason": "actor_implementation_ineligible_at_admission",
                    "actor": actor_id,
                    "details": list(admission.get("actor_ineligibility_reasons") or []),
                }
            )
        if event.get("type") == "ROLE_LEASE_ASSIGNED":
            unfinished = sorted(set(recorded_dependencies) - merged_work_units)
            if unfinished:
                violations.append(
                    {
                        "reason": "dependency_not_durably_complete_at_admission",
                        "work_unit": payload.get("work_unit"),
                        "dependencies": unfinished,
                    }
                )
        return admission, violations, None

    def add_lease(
        lease_id: str,
        actor: str | None,
        payload: dict[str, Any],
        event: dict[str, Any],
    ) -> bool:
        role = payload.get("role", "implementation")
        admission: dict[str, Any] | None = None
        if role == "implementation":
            known_implementation_leases.add(lease_id)
            candidate = snapshot_item(payload)
            admission, frozen_violations, admission_error = v2_admission(event, actor, payload)
            if admission_error:
                record_integrity_conflict(
                    event,
                    "invalid_lease_admission_evidence",
                    lease_id=lease_id,
                    detail=admission_error,
                )
                return False
            if admission is not None:
                actor_limit = int(admission.get("actor_limit"))
            else:
                actor_limit = legacy_limits.get(str(actor or ""), legacy_unknown_limit)
            violations = [
                *frozen_violations,
                *implementation_admission_violations(
                    candidate,
                    implementations(),
                    planning,
                    None,
                    actor=actor,
                    actor_limit=actor_limit,
                ),
            ]
            if violations:
                record_rejected_claim(event, lease_id, payload, violations)
                return False

        event_pr = normalize_pr(payload.get("pr"))
        active[lease_id] = {
            "id": lease_id,
            "role": role,
            "actor": actor,
            "work_unit": payload.get("work_unit"),
            "branch": payload.get("branch"),
            "pr": event_pr,
            "start_head": payload.get("start_head"),
            "planning_snapshot": payload.get("planning_snapshot", {}),
            "admission_snapshot": admission or payload.get("admission_snapshot"),
            "status": "active",
            "event": event,
        }
        if role == "implementation" and event_pr is not None and actor:
            authors_by_pr.setdefault(event_pr, set()).add(str(actor))
        return True

    for event in events:
        event_id = str(event.get("event_id") or "")
        if event_id in seen_event_ids:
            record_integrity_conflict(event, "duplicate_event_id_ignored")
            continue
        if event_id:
            seen_event_ids.add(event_id)

        event_type = event.get("type")
        actor = event.get("actor")
        payload = event.get("payload") or {}
        event_pr = normalize_pr(payload.get("pr"))
        if event_pr is not None:
            authors_by_pr.setdefault(event_pr, set())

        if event_type == "ROLE_LEASE_ASSIGNED":
            if payload.get("lease_id"):
                add_lease(str(payload.get("lease_id")), actor, payload, event)
        elif event_type == "ROLE_LEASE_RELEASED":
            if payload.get("lease_id"):
                active.pop(str(payload.get("lease_id")), None)
        elif event_type == "ROLE_LEASE_TRANSFERRED":
            old_id = str(payload.get("old_lease_id") or "")
            new_id = str(payload.get("new_lease_id") or "")
            old = active.get(old_id)
            if old is None:
                if old_id in known_implementation_leases:
                    if new_id:
                        known_implementation_leases.add(new_id)
                    record_rejected_claim(
                        event,
                        new_id,
                        payload,
                        [{"reason": "transfer_source_no_longer_active", "old_lease_id": old_id}],
                        old_lease_id=old_id,
                    )
                else:
                    record_integrity_conflict(
                        event,
                        "transfer_source_unknown",
                        old_lease_id=old_id,
                        new_lease_id=new_id,
                    )
                continue
            if old.get("role") != "implementation":
                record_integrity_conflict(
                    event,
                    "transfer_source_not_implementation",
                    old_lease_id=old_id,
                    new_lease_id=new_id,
                )
                continue
            if int(event.get("version") or 1) >= 2:
                admission = payload.get("admission_snapshot")
                if not isinstance(admission, dict) or admission.get("transfer_source_lease_id") != old_id:
                    record_integrity_conflict(
                        event,
                        "invalid_lease_admission_evidence",
                        lease_id=new_id,
                        detail="transfer admission does not bind active source lease",
                    )
                    continue
                if payload.get("planning_snapshot") != old.get("planning_snapshot"):
                    record_integrity_conflict(
                        event,
                        "invalid_lease_admission_evidence",
                        lease_id=new_id,
                        detail="transfer planning snapshot differs from canonical source lease",
                    )
                    continue
            active.pop(old_id, None)
            if new_id and not add_lease(new_id, actor, payload, event):
                active[old_id] = old
        elif event_type == "MATERIAL_AUTHOR" and event_pr is not None and actor:
            authors_by_pr[event_pr].add(str(actor))
        elif event_type == "GATE" and event_pr is not None:
            gates_by_pr[event_pr] = {
                "pr": event_pr,
                "sha": payload.get("sha"),
                "base_sha": payload.get("base_sha"),
                "reviewer_actor": actor,
                "verdict": payload.get("verdict"),
                "material_authors": payload.get("material_authors", []),
                "evidence": payload.get("evidence", []),
                "scope_verified": payload.get("scope_verified") is True,
                "changed_files": payload.get("changed_files", []),
                "summary": payload.get("summary", ""),
                "stale": False,
                "github_comment_url": event.get("github_comment_url"),
                "github_publisher": event.get("github_publisher"),
                "timestamp": event.get("github_created_at") or event.get("timestamp"),
            }
        elif event_type == "INTEGRITY_CONFLICT_RESOLVED":
            conflict_id = payload.get("conflict_id")
            if isinstance(conflict_id, str) and conflict_id:
                resolved_conflict_ids.add(conflict_id)
                open_integrity_conflicts.pop(conflict_id, None)
        elif event_type == "MERGED":
            work_unit = payload.get("work_unit")
            if isinstance(work_unit, str) and work_unit:
                merged_work_units.add(work_unit)

    for gate_pr, gate in gates_by_pr.items():
        current_authors = set(authors_by_pr.get(gate_pr, set()))
        gated_authors = set(gate.get("material_authors") or [])
        reasons: list[str] = []
        if gated_authors != current_authors:
            reasons.append("material_authorship_changed")
        if gate.get("reviewer_actor") in current_authors:
            reasons.append("reviewer_is_now_material_author")
        if reasons:
            gate["stale"] = True
            gate["stale_reasons"] = reasons

    current_actor_eligibility: dict[str, dict[str, Any]] = {}
    if enforce_actor_policy:
        all_active = implementations()
        for lease in all_active:
            lease_id = str(lease.get("id") or "")
            actor_id = str(lease.get("actor") or "")
            actor_record = actors_by_id.get(actor_id)
            if actor_record is None:
                reasons = ["unknown_actor"]
            else:
                _slots, reasons = implementation_availability(
                    actor_record,
                    readiness_by_actor.get(actor_id),
                    budget_doc,
                    all_active,
                    exclude_lease_id=lease_id,
                )
                reasons = sorted(set(reasons))
            current_actor_eligibility[lease_id] = {
                "actor": actor_id,
                "eligible": not reasons,
                "reasons": reasons,
            }

    unresolved_integrity_conflicts = list(open_integrity_conflicts.values())
    active_values = list(active.values())
    if pr is not None:
        active_values = [item for item in active_values if item.get("pr") == pr]
        authors = sorted(authors_by_pr.get(pr, set()))
        gate = gates_by_pr.get(pr)
        allowed_ids = {str(item.get("id") or "") for item in active_values}
        current_actor_eligibility = {
            key: value
            for key, value in current_actor_eligibility.items()
            if key in allowed_ids
        }
    else:
        authors = sorted({author for values in authors_by_pr.values() for author in values})
        gate = None

    return {
        "active_leases": active_values,
        "material_authors": authors,
        "current_gate": gate,
        "gates_by_pr": gates_by_pr,
        "rejected_claims": rejected_claims,
        "integrity_conflicts": unresolved_integrity_conflicts,
        "conflicts": unresolved_integrity_conflicts,
        "resolved_conflict_ids": sorted(resolved_conflict_ids),
        "merged_work_units": sorted(merged_work_units),
        "current_actor_eligibility": current_actor_eligibility,
    }
