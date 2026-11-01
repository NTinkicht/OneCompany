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
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
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


def open_control(target: Path) -> int:
    """Open ``<target>/.onecompany`` as a directory fd, refusing a symlink."""
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise ValueError("SECURE_QUEUE_READ_UNAVAILABLE")
    try:
        return os.open(target / ".onecompany", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except FileNotFoundError:
        raise ValueError("TARGET_QUEUE_NOT_FOUND") from None
    except OSError:
        raise ValueError("TARGET_QUEUE_UNSAFE") from None


def read_json(dirfd: int, name: str) -> dict:
    """Read one bounded regular file relative to the verified directory fd."""
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0), dir_fd=dirfd)
    except FileNotFoundError:
        raise ValueError("TARGET_QUEUE_NOT_FOUND" if name == "queue.json" else "TARGET_PLANNING_NOT_FOUND") from None
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
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("TARGET_QUEUE_INVALID")
    return data


def read_queue(dirfd: int) -> dict:
    queue = read_json(dirfd, "queue.json")
    units = queue.get("work_units")
    if not isinstance(units, list) or any(
            not isinstance(u, dict) or not isinstance(u.get("id"), str)
            or not isinstance(u.get("status"), str) for u in units):
        raise ValueError("TARGET_QUEUE_INVALID")
    return queue


def valid_scope(scopes: list[str] | None) -> list[str]:
    """Owner-declared bounded write scope: relative, no traversal, not a wildcard-all."""
    if not scopes:
        raise ValueError("WRITE_SCOPE_REQUIRED")
    out: list[str] = []
    for item in scopes:
        text = item.strip()
        if (not text or len(text) > 200 or text.startswith("/") or "\\" in text or "\x00" in text
                or ".." in text.split("/") or text in {"*", "**", "**/*", "./**"} or text in out):
            raise ValueError("WRITE_SCOPE_INVALID")
        out.append(text)
    if len(out) > 20:
        raise ValueError("WRITE_SCOPE_INVALID")
    return out


def build_unit(wu_id: str, brief: dict, record: dict, ref: str | None, scope: list[str]) -> dict:
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
        "planning_refs": [ref] if ref else [],
        "write_scope": scope,
        "parallelism": "serial",
        "acceptance_criteria": [answers["outcome"].strip()],
        "brief_approval": record,
    }


def plan(dirfd: int, target: Path, repository: str | None, brief_path: Path, head: str,
         base: str, wu_id: str | None, ref: str | None, scopes: list[str] | None,
         strict: bool) -> tuple[dict, dict, dict, dict | None]:
    """Re-validate everything; return (queue, portfolio, candidate, existing)."""
    assessment = analyze(target, repository=repository)
    saved = read_brief(brief_path)
    result = view(assessment, saved, str(brief_path))
    if result["stage"] != "PROPOSAL_READY_NOT_APPROVED":
        raise ValueError("COMPLETE_VALIDATED_BRIEF_REQUIRED")
    propose_brief_handoff(saved, head, base)  # exact distinct refs, full contract
    if wu_id is not None and not WU_ID.fullmatch(wu_id):
        raise ValueError("UNKNOWN_WU_ID")
    if strict and not ref:
        raise ValueError("PLANNING_REF_REQUIRED")
    scope = valid_scope(scopes) if (strict or scopes) else []
    queue = read_queue(dirfd)
    portfolio = read_json(dirfd, "portfolio.json") if ref else {}
    if ref:
        entities = portfolio.get("entities")
        if not isinstance(entities, list) or not any(
                isinstance(e, dict) and e.get("id") == ref for e in entities):
            raise ValueError("UNKNOWN_PLANNING_REF")
        if not isinstance(portfolio.get("links"), list):
            raise ValueError("TARGET_PLANNING_INVALID")
    record = {"schema": RECORD_SCHEMA, "brief_sha256": digest(saved),
              "head": head, "base": base, "owner_ack": True}
    candidate = build_unit(wu_id or "WU-UNASSIGNED", saved, record, ref, scope)
    existing = next((u for u in queue["work_units"] if u["id"] == wu_id), None) if wu_id else None
    if existing is not None:
        if existing != candidate:
            raise ValueError("WU_ID_EXISTS_WITH_DIFFERENT_APPROVAL")
        return queue, portfolio, candidate, existing
    if any(u["status"] not in FINISHED for u in queue["work_units"]):
        raise ValueError("ACTIVE_WU_STREAM_PRESENT")
    return queue, portfolio, candidate, None


def write_json(dirfd: int, name: str, data: dict) -> None:
    """Replace a control file atomically, anchored to the verified directory fd."""
    tmp = f".{name}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=dirfd)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.rename(tmp, name, src_dir_fd=dirfd, dst_dir_fd=dirfd)
    except BaseException:
        try:
            os.unlink(tmp, dir_fd=dirfd)
        except OSError:
            pass
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
    parser.add_argument("--planning-ref", help="Existing portfolio entity this WU traces to")
    parser.add_argument("--write-scope", action="append", help="Owner-approved relative path/glob (repeatable)")
    args = parser.parse_args(argv)
    target = Path(args.target).resolve()
    apply = bool(args.owner_ack and args.approve_wu)
    dirfd = -1
    lockfd = -1
    try:
        dirfd = open_control(target)
        common = (dirfd, target, args.repository, args.brief, args.head, args.base,
                  args.approve_wu, args.planning_ref, args.write_scope)
        if apply:
            lockfd = os.open(".brief-approval.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600, dir_fd=dirfd)
            fcntl.flock(lockfd, fcntl.LOCK_EX)  # serialize the whole read/check/write
        queue, portfolio, candidate, existing = plan(*common, strict=apply)
        if existing is not None:
            print(json.dumps({"result": "ALREADY_ADMITTED", "work_unit": existing}, sort_keys=True))
            return 0
        if not apply:
            print(json.dumps({"result": "PREVIEW_NOTHING_CHANGED", "would_admit": candidate}, sort_keys=True))
            return 2
        link = {"source": args.planning_ref, "target": args.approve_wu, "relationship": "delivers",
                "rationale": "Owner-acknowledged brief approval."}
        if not any(l == link for l in portfolio["links"]):
            portfolio["links"].append(link)
            write_json(dirfd, "portfolio.json", portfolio)
        queue["work_units"].append(candidate)
        write_json(dirfd, "queue.json", queue)
    except (ValueError, OSError, TypeError, UnicodeError, KeyError, RecursionError) as exc:
        print("REFUSED: " + str(exc), file=sys.stderr)
        return 2
    finally:
        for fd in (lockfd, dirfd):
            if fd >= 0:
                os.close(fd)
    print(json.dumps({"result": "ADMITTED", "work_unit": candidate}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
