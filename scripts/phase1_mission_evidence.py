#!/usr/bin/env python3
"""Compose real Phase-1 local evidence into an honest read-only Mission Control view."""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path

from mission_control_local import combine_projection_journey
from mission_control_projection import project

MAX_INPUT_BYTES = 65_536
_SHA = re.compile(r"^[0-9a-f]{40}$")


def read_object(path: Path) -> dict:
    """Read one bounded regular JSON file without following symlinks."""
    if not hasattr(os, "O_NOFOLLOW"):
        raise ValueError("SECURE_EVIDENCE_READ_UNAVAILABLE")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0))
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("EVIDENCE_REGULAR_FILE_REQUIRED")
        with os.fdopen(fd, "rb", closefd=False) as source:
            raw = source.read(MAX_INPUT_BYTES + 1)
    finally:
        os.close(fd)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("EVIDENCE_TOO_LARGE")
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("EVIDENCE_OBJECT_REQUIRED")
    return result


def compose(smoke: dict, revision: str, quality: dict | None = None,
            journey: dict | None = None) -> dict:
    """Display measured local effects, never infer implementation approval or live CI."""
    if not isinstance(revision, str) or not _SHA.fullmatch(revision):
        raise ValueError("EXACT_CALLER_REVISION_REQUIRED")
    if not isinstance(smoke, dict) or smoke.get("schema") != "onecompany.phase1-vertical-smoke.v1":
        raise ValueError("CANONICAL_LOCAL_SMOKE_REQUIRED")
    refs = smoke.get("source_refs_unverified")
    http = smoke.get("real_local_http")
    planning = smoke.get("planning")
    source_project = smoke.get("project")
    if (not isinstance(refs, dict) or refs.get("head") != revision
            or not isinstance(refs.get("base"), str)
            or not _SHA.fullmatch(refs["base"])
            or refs["base"] == revision):
        raise ValueError("LOCAL_SMOKE_REVISION_MISMATCH")
    if (smoke.get("status") != "LOCAL_FIXTURE_PROVEN_ONLY"
            or smoke.get("path") not in {"create", "adopt"}
            or smoke.get("owner_brief") != "VALID_DRAFT_NOT_APPROVED"
            or not isinstance(source_project, dict)
            or not isinstance(source_project.get("name"), str)
            or not isinstance(planning, dict)
            or planning.get("mode") != "READ_ONLY_PROPOSAL"
            or planning.get("authorization") != "NOT_GRANTED"
            or not isinstance(http, dict)
            or http.get("status") != "PASS" or http.get("health") != "PASS"
            or http.get("fixture_discarded") is not True
            or smoke.get("owner_implementation_approved") is not False
            or smoke.get("canonical_work_unit") is not None
            or smoke.get("run_key") is not None
            or smoke.get("lease_id") is not None
            or smoke.get("deployable") is not False
            or smoke.get("requested_extra_spend") != 0):
        raise ValueError("UNAUTHORIZED_OR_INCOMPLETE_LOCAL_SMOKE")
    quality_pass = False
    if quality is not None:
        if (not isinstance(quality, dict)
                or quality.get("schema") != "onecompany.local-quality-evidence.v1"
                or quality.get("revision") != revision
                or quality.get("status") != "PASS"
                or quality.get("scope") != "real_local_http_ui"
                or quality.get("deployable") is not False):
            raise ValueError("QUALITY_EVIDENCE_NOT_EXACT_OR_NOT_LOCAL")
        quality_pass = True
    evidence = {
        "app": {"revision": revision, "status": "PASS"},
        "preview": {"revision": revision, "status": "PASS"},
        "quality": {"revision": revision, "status": "PASS" if quality_pass else "BLOCKED"},
    }
    # Bounded means only the disposable fixture executed within local boundaries.
    # The projection remains non-authoritative even if every local check passes.
    result = project(revision, {"status": "DRAFT", "approved": False},
                     {"bounded": True}, evidence)
    if journey is not None:
        if (not isinstance(journey, dict)
                or journey.get("project") != source_project):
            raise ValueError("JOURNEY_PROJECT_MISMATCH")
        result = combine_projection_journey(result, journey)
    else:
        result["project"] = {"name": source_project["name"]}
        result["stage"] = "LOCAL_FIXTURE_PROVEN_ONLY"
        result["steps"] = [
            {"title": "Confirm owner authorization", "status": "not_granted"},
            {"title": "Verify exact-head CI and nonauthor review", "status": "unknown"},
        ]
    blockers = list(result.get("blockers", []))
    if not quality_pass:
        blockers.append("Exact clean-checkout local quality evidence is missing.")
    blockers.append("No owner approval, canonical Work Unit/lease, verified GitHub refs, CI or independent review was established by this demonstration.")
    result["blockers"] = blockers
    result["next_action"] = (
        "Verify actual GitHub refs and independent exact-head CI/review, then seek explicit owner authorization; this local demonstration cannot approve or deploy."
    )
    result["authority_granted"] = False
    result["local_fixture_discarded"] = True
    result["source_refs_unverified"] = True
    # An already stopped fixture has no usable URL; never show its stale port.
    result.pop("preview_url", None)
    return result


def main(argv: list[str] | None = None) -> int:
    """Produce a JSON dashboard input from existing smoke and optional quality."""
    parser = argparse.ArgumentParser(description="Compose read-only Phase-1 Mission Control local evidence")
    parser.add_argument("--smoke", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--quality", type=Path)
    parser.add_argument("--journey", type=Path)
    args = parser.parse_args(argv)
    try:
        result = compose(
            read_object(args.smoke), args.revision,
            read_object(args.quality) if args.quality else None,
            read_object(args.journey) if args.journey else None,
        )
    except (OSError, ValueError, TypeError, KeyError, RecursionError, UnicodeError) as exc:
        print("BLOCKED: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
