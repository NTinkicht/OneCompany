#!/usr/bin/env python3
"""Wake OneCompany from GitHub events and reconcile authoritative state safely.

GitHub event payloads are wake hints only. This runtime uses them solely to choose
a reconciliation class and diagnostic subject; all consequential state is rebuilt
by ``supervise.py`` from live GitHub plus durable coordination truth.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import handoff
from onecompany_lib import CONTROL, load_json

ROOT = Path(__file__).resolve().parents[1]
SUPERVISE = ROOT / "scripts" / "supervise.py"
POST_SAFE_EVENTS = {"schedule", "push", "workflow_run", "workflow_dispatch"}


def load_event(path: str | None) -> dict[str, Any]:
    """Load an event only as an untrusted wake hint."""
    if not path:
        return {}
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read GitHub event hint: {exc}") from exc
    return value if isinstance(value, dict) else {}


def event_kind(event_name: str, action: str | None, payload: dict[str, Any]) -> str:
    """Map a platform wake signal to a reconciliation kind without granting authority."""
    if event_name == "pull_request_review":
        return "REVIEW_CHANGED"
    if event_name == "workflow_run":
        return "CI_CHANGED"
    if event_name == "pull_request":
        if action == "closed":
            return "MERGE_CHANGED"
        return "PR_CHANGED"
    if event_name in {"push", "schedule", "workflow_dispatch", "repository_dispatch"}:
        return "RECONCILE"
    return "RECONCILE"


def event_subject(event_name: str, payload: dict[str, Any]) -> str:
    """Derive a diagnostic subject only; this value is never authority."""
    pr = payload.get("pull_request")
    if isinstance(pr, dict) and isinstance(pr.get("number"), int):
        return f"pr:{pr['number']}"
    workflow = payload.get("workflow_run")
    if isinstance(workflow, dict) and isinstance(workflow.get("id"), int):
        return f"workflow_run:{workflow['id']}"
    ref = payload.get("ref")
    if isinstance(ref, str) and ref:
        return f"ref:{ref}"
    return f"event:{event_name or 'unknown'}"


def wake_id(delivery_id: str, event_name: str, action: str | None, subject: str) -> str:
    """Create deterministic wake identity for replica/delivery deduplication evidence."""
    material = json.dumps(
        {"delivery": delivery_id, "event": event_name, "action": action, "subject": subject},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "wake-" + hashlib.sha256(material).hexdigest()


def run_supervision(*, post_team_room: bool = False) -> dict[str, Any]:
    """Reconcile from live/durable authority; optionally post a non-authoritative signal."""
    base = [sys.executable, str(SUPERVISE)]
    result = subprocess.run(base, cwd=str(ROOT), text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "supervision failed")
    try:
        snapshot = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("supervision did not return JSON") from exc
    if not isinstance(snapshot, dict):
        raise RuntimeError("supervision snapshot must be an object")

    if post_team_room:
        posted = subprocess.run(
            [*base, "--post-team-room"],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            check=False,
        )
        if posted.returncode != 0:
            raise RuntimeError(posted.stderr.strip() or posted.stdout.strip() or "Team Room post failed")
    return snapshot


def reconcile_event(
    event_name: str,
    action: str | None,
    payload: dict[str, Any],
    delivery_id: str,
    *,
    post_team_room: bool = False,
) -> dict[str, Any]:
    """Reconcile one wake signal while keeping L1 mutation authority disabled."""
    policy = handoff.load_policy()
    supervision = load_json(CONTROL / "supervision.json")
    if not handoff.activation_ready(policy):
        raise RuntimeError("B2 handoff activation is not ready")
    if supervision.get("enabled") is not True:
        raise RuntimeError("B3 supervision is not enabled")

    kind = event_kind(event_name, action, payload)
    subject = event_subject(event_name, payload)
    safe_post = post_team_room and event_name in POST_SAFE_EVENTS
    snapshot = run_supervision(post_team_room=safe_post)
    return {
        "schema": "onecompany-event-reconciliation-v1",
        "authority": "none",
        "authority_effects": [],
        "wake": {
            "id": wake_id(delivery_id, event_name, action, subject),
            "event_name": event_name,
            "event_action": action,
            "kind": kind,
            "subject": subject,
            "payload_used_as_authority": False,
        },
        "activation_state": "ACTIVE",
        "supervision": snapshot,
        "autonomy_level": "L1",
        "mutation_authorized": False,
        "automatic_failover_authorized": False,
        "automatic_merge_authorized": False,
        "human_sovereignty_preserved": True,
        "zero_extra_spend_required": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcile OneCompany from one GitHub wake event")
    parser.add_argument("--event-name", default=os.environ.get("GITHUB_EVENT_NAME", "workflow_dispatch"))
    parser.add_argument("--event-action", default="")
    parser.add_argument("--event-path", default=os.environ.get("GITHUB_EVENT_PATH"))
    parser.add_argument("--delivery-id", default=os.environ.get("GITHUB_RUN_ID", "manual"))
    parser.add_argument("--post-team-room", action="store_true")
    args = parser.parse_args()
    try:
        payload = load_event(args.event_path)
        output = reconcile_event(
            args.event_name,
            args.event_action or None,
            payload,
            args.delivery_id,
            post_team_room=args.post_team_room,
        )
        print(json.dumps(output, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"HANDOFF RUNTIME BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
