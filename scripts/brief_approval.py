#!/usr/bin/env python3
"""Owner-acknowledged admission of exactly one bounded WU from a saved brief.

Local and offline: no network, provider call, credential read or spend. The
command re-opens the saved brief securely, re-assesses the target at the same
boundary as ``journey`` and only then (with both explicit flags) appends one
READY work unit to the target's existing ``.onecompany/queue.json``. It never
creates a lease, RunKey, dispatch, worker run or merge decision.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path

from onboard import analyze
from brief_handoff_proposal import propose as propose_brief_handoff
from first_run_journey import read_brief, view

WU_ID = re.compile(r"WU[0-9A-Za-z._-]{1,80}\Z")
FINISHED = frozenset({"DONE", "MERGED", "CANCELLED"})
MAX_QUEUE_BYTES = 1_048_576
RECORD_SCHEMA = "onecompany.brief-approval.v1"


def digest(brief: dict) -> str:
    """Bind approval to the exact canonical content of the saved brief."""
    raw = json.dumps(brief, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def read_queue(path: Path) -> dict:
    """Read the target queue as one bounded regular file, never via a symlink."""
    if not hasattr(os, "O_NOFOLLOW"):
        raise ValueError("SECURE_QUEUE_READ_UNAVAILABLE")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0))
    except FileNotFoundError:
        raise ValueError("TARGET_QUEUE_NOT_FOUND") from None
    except OSError:
        raise ValueError("TARGET_QUEUE_UNSAFE") from None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("TARGET_QUEUE_UNSAFE")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(MAX_QUEUE_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(raw) > MAX_QUEUE_BYTES:
        raise ValueError("TARGET_QUEUE_TOO_LARGE")
    queue = json.loads(raw)
    units = queue.get("work_units") if isinstance(queue, dict) else None
    if not isinstance(units, list) or any(
            not isinstance(u, dict) or not isinstance(u.get("id"), str)
            or not isinstance(u.get("status"), str) for u in units):
        raise ValueError("TARGET_QUEUE_INVALID")
    return queue


def build_unit(wu_id: str, brief: dict, record: dict) -> dict:
    """Build the READY unit; acceptance criteria are the owner's words only."""
    answers = brief["answers"]
    title = "Deliver first feature: " + answers["first_feature"].strip()
    return {
        "id": wu_id,
        "title": title[:120],
        "work_kind": "DELIVERY",
        "status": "READY",
        "priority": 100,
        "dependencies": [],
        "issue": None,
        "pr": None,
        "branch": None,
        "risk_class": "MEDIUM",
        "acceptance_criteria": [answers["outcome"].strip()],
        "brief_approval": record,
    }


def plan(target: Path, repository: str | None, brief_path: Path, head: str,
         base: str, wu_id: str | None) -> tuple[dict, dict, dict | None]:
    """Re-validate everything; return (queue, candidate unit, existing unit)."""
    assessment = analyze(target, repository=repository)
    saved = read_brief(brief_path)
    result = view(assessment, saved, str(brief_path))
    if result["stage"] != "PROPOSAL_READY_NOT_APPROVED":
        raise ValueError("COMPLETE_VALIDATED_BRIEF_REQUIRED")
    propose_brief_handoff(saved, head, base)  # exact distinct refs, full contract
    if wu_id is not None and not WU_ID.fullmatch(wu_id):
        raise ValueError("UNKNOWN_WU_ID")
    queue = read_queue(target / ".onecompany" / "queue.json")
    record = {"schema": RECORD_SCHEMA, "brief_sha256": digest(saved),
              "head": head, "base": base, "owner_ack": True}
    candidate = build_unit(wu_id or "WU-UNASSIGNED", saved, record)
    existing = next((u for u in queue["work_units"] if u["id"] == wu_id), None) if wu_id else None
    if existing is not None:
        if existing.get("brief_approval") != record:
            raise ValueError("WU_ID_EXISTS_WITH_DIFFERENT_APPROVAL")
        return queue, candidate, existing
    if any(u["status"] not in FINISHED for u in queue["work_units"]):
        raise ValueError("ACTIVE_WU_STREAM_PRESENT")
    return queue, candidate, None


def write_queue(path: Path, queue: dict) -> None:
    """Replace the queue atomically inside the same directory."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".queue.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(queue, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main(argv: list[str] | None = None) -> int:
    """Preview by default; admit one WU only with --approve-wu and --owner-ack."""
    parser = argparse.ArgumentParser(description="Admit one bounded WU from an owner-approved brief")
    parser.add_argument("--target", default=".")
    parser.add_argument("--repository")
    parser.add_argument("--brief", required=True, type=Path)
    parser.add_argument("--head", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--approve-wu")
    parser.add_argument("--owner-ack", action="store_true")
    args = parser.parse_args(argv)
    target = Path(args.target).resolve()
    try:
        queue, candidate, existing = plan(target, args.repository, args.brief,
                                          args.head, args.base, args.approve_wu)
        if existing is not None:
            print(json.dumps({"result": "ALREADY_ADMITTED", "work_unit": existing}, sort_keys=True))
            return 0
        if not (args.owner_ack and args.approve_wu):
            print(json.dumps({"result": "PREVIEW_NOTHING_CHANGED", "would_admit": candidate}, sort_keys=True))
            return 2
        queue["work_units"].append(candidate)
        write_queue(target / ".onecompany" / "queue.json", queue)
    except (ValueError, OSError, TypeError, UnicodeError, KeyError, RecursionError) as exc:
        print("REFUSED: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps({"result": "ADMITTED", "work_unit": candidate}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
