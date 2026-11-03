#!/usr/bin/env python3
"""Read-only per-WU Mission Control truth projection (OC-P0-17).

Compares cached work-unit claims with a live GitHub observation. Callers must
obtain both from trusted sources; this module fetches, merges and admits
nothing, and never reports success it cannot verify against live data.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from live_work_reconciliation import _same_sha, snapshot_freshness  # noqa: E402

SCHEMA = "onecompany.mission-truth.v1"
_RISKS = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


def _ts(value: object) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _row(wu: dict, live_pr: object, live_findings: tuple[str, ...], live_at: dt.datetime | None) -> dict:
    claimed = wu.get("claimed_state")
    problems: list[str] = list(live_findings)
    state = "OPEN"
    if wu.get("blockers"):
        state = "BLOCKED"
    if claimed == "MERGED":
        cached_at = _ts(wu.get("cached_at"))
        if cached_at is None:
            problems.append("INVALID_CACHE_TIMESTAMP")
        elif live_at is not None and live_at < cached_at:
            problems.append("OUT_OF_ORDER_EVENT")
        if problems:
            state = "UNABLE_TO_VERIFY"
        elif not isinstance(live_pr, dict):
            state = "UNABLE_TO_VERIFY"
            problems.append("NO_LIVE_OBSERVATION")
        elif (live_pr.get("merged") is True
              and _same_sha(wu.get("head_sha"), live_pr.get("head_sha"))
              and _same_sha(wu.get("merge_sha"), live_pr.get("merge_sha"))):
            state = "VERIFIED_MERGED"
        else:
            state = "DRIFT"
            problems.append("LIVE_DISAGREES_WITH_CACHE")
    raw_risk = wu.get("risk_class", wu.get("risk"))
    risk = raw_risk if raw_risk in _RISKS else "CRITICAL"
    # Higher static priority first, matching planning_lib.rank_work.
    priority = wu.get("priority") if type(wu.get("priority")) is int else 0
    if state == "VERIFIED_MERGED":
        action = "NONE"
    elif state == "BLOCKED":
        action = "RESOLVE_BLOCKERS"
    elif state == "OPEN":
        action = "CONTINUE_WORK"
    elif state == "DRIFT":
        action = "RECONCILE_CACHE_WITH_GITHUB"
    else:
        action = "REFRESH_LIVE_OBSERVATION"
    return {
        "id": wu.get("id"), "state": state, "priority": priority, "risk": risk,
        "blockers": sorted(str(b) for b in wu.get("blockers") or []),
        "findings": sorted(set(problems)), "next_action": action,
    }


def project_work_units(cache: object, live: object, now: dt.datetime,
                       max_age_seconds: int) -> dict:
    """Project cached WU claims against a live observation, failing closed."""
    if not isinstance(cache, list) or not all(
            isinstance(w, dict) and isinstance(w.get("id"), str) and w["id"] for w in cache):
        raise ValueError("WORK_UNIT_LIST_REQUIRED")
    ids = [w["id"] for w in cache]
    if len(ids) != len(set(ids)):
        raise ValueError("DUPLICATE_WORK_UNIT")
    live = live if isinstance(live, dict) else {}
    live_at = _ts(live.get("observed_at"))
    findings = snapshot_freshness(live_at, now, max_age_seconds) if live_at else ("INVALID_TIMESTAMP",)
    prs = live.get("prs") if isinstance(live.get("prs"), dict) else {}
    rows = [_row(w, prs.get(w["id"]), findings, live_at) for w in cache]
    rows.sort(key=lambda r: (-r["priority"], -_RISKS[r["risk"]], r["id"]))
    verified = all(r["state"] == "VERIFIED_MERGED" for r in rows) if rows else False
    return {
        "schema": SCHEMA, "work_units": rows, "all_verified": verified,
        "next_action": next((r["next_action"] for r in rows if r["next_action"] != "NONE"), "NONE"),
        "authority_granted": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Project per-WU mission truth (read-only)")
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--live", type=Path, required=True)
    parser.add_argument("--max-age-seconds", type=int, default=900)
    args = parser.parse_args(argv)
    try:
        cache = json.loads(args.cache.read_text(encoding="utf-8"))
        live = json.loads(args.live.read_text(encoding="utf-8"))
        result = project_work_units(cache, live, dt.datetime.now(dt.timezone.utc),
                                    args.max_age_seconds)
    except (OSError, ValueError) as exc:
        print(f"MISSION_TRUTH_INPUT_REJECTED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
