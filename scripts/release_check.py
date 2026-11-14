#!/usr/bin/env python3
"""Deterministic, read-only release / incident readiness check (OC-P0-18, #421).

Verifies that the documented release and incident drills still match the
repository: every ``python onecompany.py <command>`` named in the release
checklist or the incident runbook is a registered command, the emergency-stop
flag is a boolean, the required sections exist and every referenced doc path
exists. No network, no writes, never clears the stop flag.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ("docs/RELEASE-CHECKLIST.md", "docs/INCIDENT-RUNBOOK.md")
REQUIRED_SECTIONS = {
    "docs/RELEASE-CHECKLIST.md": ("## Trusted control plane", "## Deterministic acceptance", "## Final promotion"),
    "docs/INCIDENT-RUNBOOK.md": ("## 1. Contain first", "## 4. Recover with a reversible path",
                                 "## 6. Restore autonomy gradually"),
}
COMMAND = re.compile(r"python3? onecompany\.py ([A-Za-z0-9_.:/-]+)")
DOC_PATH = re.compile(r"`((?:docs|scripts)/[A-Za-z0-9_./-]+\.(?:md|py|json))`")


def registered_commands(root: Path) -> set[str]:
    """Read the COMMANDS table of onecompany.py statically (never imports or executes it)."""
    tree = ast.parse((root / "onecompany.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "COMMANDS" for t in node.targets):
            if isinstance(node.value, ast.Dict):
                return {key.value for key in node.value.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)}
    return set()


EVIDENCE_MAX_BYTES = 1_000_000
SHA = re.compile(r"[0-9a-f]{40}")
ENVIRONMENTS = ("staging", "test")


def _load_evidence(path: Path):
    """Read a bounded regular non-symlink JSON file; return (data, finding)."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except OSError:
        return None, "EVIDENCE_UNREADABLE"
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None, "EVIDENCE_UNREADABLE"
        with os.fdopen(fd, "rb", closefd=False) as handle:
            raw = handle.read(EVIDENCE_MAX_BYTES + 1)
    except OSError:
        return None, "EVIDENCE_UNREADABLE"
    finally:
        os.close(fd)
    if len(raw) > EVIDENCE_MAX_BYTES:
        return None, "EVIDENCE_TOO_LARGE"
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None, "EVIDENCE_MALFORMED"
    if not isinstance(data, dict):
        return None, "EVIDENCE_NOT_OBJECT"
    return data, None


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def check_evidence(evidence, now: datetime, stop_flag=None) -> list[str]:
    """Refuse a release unless the evidence proves a fresh, green, drilled staging/test release."""
    findings: set[str] = set()
    obj = lambda value: value if isinstance(value, dict) else {}  # noqa: E731
    top = obj(evidence)
    head = top.get("head_sha")
    if not (isinstance(head, str) and SHA.fullmatch(head)):
        findings.add("HEAD_SHA_INVALID")
    if not (isinstance(top.get("release_version"), str) and top["release_version"].strip()):
        findings.add("RELEASE_VERSION_MISSING")
    if top.get("environment") not in ENVIRONMENTS:
        findings.add("ENVIRONMENT_NOT_STAGING_OR_TEST")
    ci, review, provider = obj(top.get("ci")), obj(top.get("review")), obj(top.get("provider"))
    if ci.get("conclusion") != "success":
        findings.add("CI_NOT_GREEN")
    if ci.get("head_sha") != head:
        findings.add("CI_HEAD_MISMATCH")
    if review.get("state") != "APPROVED":
        findings.add("REVIEW_NOT_APPROVED")
    if review.get("head_sha") != head:
        findings.add("REVIEW_HEAD_MISMATCH")
    if provider.get("status") != "up":
        findings.add("PROVIDER_NOT_HEALTHY")
    rollback, stop, backup = obj(top.get("rollback_drill")), obj(top.get("stop_drill")), obj(top.get("backup"))
    if rollback.get("passed") is not True:
        findings.add("ROLLBACK_DRILL_NOT_PASSED")
    if not (isinstance(rollback.get("previous_version"), str) and rollback["previous_version"].strip()):
        findings.add("ROLLBACK_PREVIOUS_VERSION_MISSING")
    if stop.get("passed") is not True:
        findings.add("STOP_DRILL_NOT_PASSED")
    if backup.get("verified") is not True:
        findings.add("BACKUP_NOT_VERIFIED")
    if top.get("emergency_stop_active") is not False or stop_flag is True:
        findings.add("EMERGENCY_STOP_ACTIVE")
    observed, max_age = _timestamp(top.get("observed_at")), top.get("max_age_seconds")
    if observed is None or type(max_age) is not int or max_age <= 0:
        findings.add("EVIDENCE_TIME_INVALID")
    elif observed > now:
        findings.add("EVIDENCE_FROM_FUTURE")
    elif (now - observed).total_seconds() > max_age:
        findings.add("EVIDENCE_STALE")
    return sorted(findings)


def check(root: Path) -> list[str]:
    """Return sorted findings (stable codes); an empty list means ready."""
    findings: set[str] = set()
    commands = registered_commands(root)
    if not commands:
        findings.add("COMMAND_REGISTRY_UNREADABLE")
    try:
        config = json.loads((root / ".onecompany" / "config.json").read_text(encoding="utf-8"))
        flag = (config.get("safety") or {}).get("emergency_stop") if isinstance(config, dict) else None
    except (OSError, ValueError):
        flag = None
    if type(flag) is not bool:
        findings.add("EMERGENCY_STOP_NOT_BOOLEAN")
    for doc in DOCS:
        path = root / doc
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            findings.add(f"DOC_MISSING:{doc}")
            continue
        for section in REQUIRED_SECTIONS[doc]:
            if section not in text.splitlines():
                findings.add(f"SECTION_MISSING:{doc}:{section.lstrip('# ').strip()}")
        for command in COMMAND.findall(text):
            if commands and command not in commands:
                findings.add(f"UNKNOWN_COMMAND:{doc}:{command}")
        for ref in DOC_PATH.findall(text):
            target = (root / ref).resolve()
            if not target.is_relative_to(root.resolve()):
                findings.add(f"REFERENCED_PATH_OUTSIDE_REPO:{doc}:{ref}")
            elif not target.is_file():
                findings.add(f"REFERENCED_PATH_MISSING:{doc}:{ref}")
    return sorted(findings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only release/incident readiness check.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    parser.add_argument("--evidence", help="also gate a release-evidence JSON file (staging/test only)")
    parser.add_argument("--now", help="ISO-8601 time with offset for deterministic freshness checks")
    args = parser.parse_args(argv)
    findings = check(ROOT)
    if args.evidence:
        now = _timestamp(args.now) if args.now else datetime.now(timezone.utc)
        data, problem = _load_evidence(Path(args.evidence))
        if now is None:
            findings.append("NOW_INVALID")
        elif problem:
            findings.append(problem)
        else:
            try:
                flag = (json.loads((ROOT / ".onecompany" / "config.json").read_text(encoding="utf-8")).get("safety") or {}).get("emergency_stop")
            except (OSError, ValueError, AttributeError):
                flag = None
            findings.extend(check_evidence(data, now, flag))
        findings = sorted(set(findings))
    if args.json:
        print(json.dumps({"ready": not findings, "findings": findings}, sort_keys=True))
    elif findings:
        print("release-check: NOT READY")
        for finding in findings:
            print(f"  {finding}")
    else:
        print("release-check: READY (read-only; no stop flag cleared, no network)")
    return 0 if not findings else 1


if __name__ == "__main__":
    sys.exit(main())
