#!/usr/bin/env python3
"""Read-only L5 V2 Phase 2 labeled-shadow agreement report.

Consumes *supplied* evidence; never opens a GitHub connection, mints a token,
mutates the controller state, or declares production L5 qualification. A score
is a numerical candidate only, not independent proof of three live days.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

ALLOWED_REPOS = frozenset({"NTinkicht/OneCompany", "NTinkicht/Tabibi", "NTinkicht/veritas-atlas"})
FIELDS = frozenset({"run_id", "repository", "day", "labeled_decision", "shadow_decision"})
IDENTIFIER = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:/-]{0,127}$")


def evaluate(payload: Any) -> dict:
    if not isinstance(payload, dict) or set(payload) != {"schema", "records"}:
        raise ValueError("SHADOW_INPUT_SCHEMA_INVALID")
    if payload["schema"] != "L5_SHADOW_LABELS_V1":
        raise ValueError("SHADOW_SCHEMA_VERSION_UNSUPPORTED")
    rows = payload["records"]
    if not isinstance(rows, list) or len(rows) > 100_000:
        raise ValueError("SHADOW_RECORDS_INVALID")
    per_repo: dict[str, list[dict]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != FIELDS:
            raise ValueError("SHADOW_RECORD_FIELDS_INVALID")
        repo = row["repository"]
        if repo not in ALLOWED_REPOS:
            raise ValueError("SHADOW_TARGET_NOT_ALLOWED")
        run = row["run_id"]
        label, candidate = row["labeled_decision"], row["shadow_decision"]
        if not all(isinstance(s, str) and IDENTIFIER.fullmatch(s) for s in (run, label, candidate)):
            raise ValueError("SHADOW_DECISION_OR_RUN_INVALID")
        day = row["day"]
        if not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise ValueError("SHADOW_DAY_INVALID")
        try:
            if date.fromisoformat(day).isoformat() != day:
                raise ValueError("SHADOW_DAY_INVALID")
        except ValueError as exc:
            raise ValueError("SHADOW_DAY_INVALID") from exc
        key = (repo, run)
        if key in seen:
            raise ValueError("SHADOW_DUPLICATE_RUN_ID")
        seen.add(key)
        per_repo[repo].append(row)
    results = {}
    for repo in sorted(ALLOWED_REPOS):
        samples = per_repo[repo]
        total = len(samples)
        matches = sum(r["labeled_decision"] == r["shadow_decision"] for r in samples)
        days = len({r["day"] for r in samples})
        # Exact integer comparison avoids float rounding over the 95% gate.
        score_pass = total > 0 and matches * 100 >= total * 95
        results[repo] = {
            "samples": total,
            "matching": matches,
            "distinct_days": days,
            "agreement_percent": round(matches * 100 / total, 3) if total else None,
            "numerical_candidate": days >= 3 and score_pass,
        }
    return {
        "schema": "L5_SHADOW_AGREEMENT_REPORT_V1",
        "mode": "READ_ONLY",
        "mutations": 0,
        "results": results,
        "production_l5_certified": False,
        "reason": "SOURCE_AUTHENTICITY_AND_LIVE_3_DAY_WINDOW_NOT_PROVEN_BY_OFFLINE_LABELS",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only L5 shadow agreement report")
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()
    try:
        output = evaluate(json.loads(args.evidence.read_text(encoding="utf-8")))
    except (OSError, ValueError, UnicodeError) as exc:
        print(json.dumps({"status": "INVALID_EVIDENCE", "reason": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(output, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
