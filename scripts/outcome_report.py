#!/usr/bin/env python3
"""Deterministic, read-only outcome / budget report from supplied receipts (OC-P1-08, #423).

Computes per-WU outcome, start->end latency and cost-class totals only from the
receipts given. Enforces the zero-spend policy in ``.onecompany/budget.json``,
never estimates tokens/cost, never prints fields outside an allow-list, and
labels confidence ``low`` when events or timestamps are missing. No network,
no writes, no clock.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
START_EVENTS = {"start", "started", "claimed"}
END_EVENTS = {"end", "merged", "failed", "abandoned"}
INCIDENT_EVENTS = {"incident"}
PENDING_EVENTS = {"gate_pending"}
SECRET_LIKE = re.compile(r"(gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{16,}|Bearer\s+\S+|AKIA[0-9A-Z]{16})")
SAFE_ID = re.compile(r"^[A-Za-z0-9_.:#/-]{1,80}$")


def _median(values):
    n = len(values)
    if n % 2:
        return values[n // 2]
    total = values[n // 2 - 1] + values[n // 2]
    return total // 2 if total % 2 == 0 else total / 2


def parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def safe_text(value: object, default: str = "unknown") -> str:
    """Return an allow-listed identifier; anything secret-like or oddly shaped is replaced."""
    if isinstance(value, str) and SAFE_ID.match(value) and not SECRET_LIKE.search(value):
        return value
    return default if not isinstance(value, str) or not value else "[redacted]"


def load_budget(root: Path) -> tuple[set[str], set[str]]:
    classes = json.loads((root / ".onecompany" / "budget.json").read_text(encoding="utf-8")).get("cost_classes", {})
    return set(classes.get("allowed", [])), set(classes.get("forbidden", []))


def build_report(receipts: object, allowed: set[str], forbidden: set[str]) -> dict:
    if not isinstance(receipts, list):
        raise ValueError("receipts must be a JSON list")
    per_wu: dict[str, dict] = {}
    violations: list[dict] = []
    for index, raw in enumerate(receipts):
        r = raw if isinstance(raw, dict) else {}
        raw_wu = r.get("wu")
        wu = raw_wu if isinstance(raw_wu, str) and raw_wu else None
        event = safe_text(r.get("event"))
        wu_row = per_wu.setdefault(wu, {"starts": [], "ends": [], "incidents": 0,
                                        "pending_gates": 0, "cost_classes": {}, "tokens": 0, "tokens_known": False,
                                        "bad_timestamps": 0, "events": 0})
        wu_row["events"] += 1
        when = parse_time(r.get("at"))
        if when is None:
            wu_row["bad_timestamps"] += 1
        if event in START_EVENTS and when:
            wu_row["starts"].append(when)
        if event in END_EVENTS:
            if when:
                wu_row["ends"].append((when, safe_text(r.get("outcome"), event)))
        if event in INCIDENT_EVENTS:
            wu_row["incidents"] += 1
        if event in PENDING_EVENTS:
            wu_row["pending_gates"] += 1
        cost_class = r.get("cost_class")
        shown = safe_text(cost_class, "MISSING")
        wu_row["cost_classes"][shown] = wu_row["cost_classes"].get(shown, 0) + 1
        if not isinstance(cost_class, str) or cost_class in forbidden or cost_class not in allowed:
            violations.append({"index": index, "wu_key": wu, "cost_class": shown, "reason": "cost class missing, forbidden or not allowed"})
        tokens = r.get("tokens")
        if isinstance(tokens, int) and not isinstance(tokens, bool) and tokens >= 0:
            wu_row["tokens"] += tokens
            wu_row["tokens_known"] = True

    # Aggregate on the raw identity; only the displayed name is redacted, and each redacted
    # identity gets its own stable label so unrelated work units are never merged.
    keys = sorted(per_wu, key=lambda k: (k is None, k or ""))
    labels: dict[str | None, str] = {}
    redacted = 0
    for key in keys:
        shown = safe_text(key)
        if shown == "[redacted]":
            redacted += 1
            shown = f"[redacted-{redacted}]"
        labels[key] = shown
    rows = []
    for key in keys:
        row = per_wu[key]
        wu = labels[key]
        latency = None
        outcome = None
        if row["starts"] and row["ends"]:
            last_end = max(when for when, _ in row["ends"])
            delta = (last_end - min(row["starts"])).total_seconds()
            latency = int(delta) if delta >= 0 else None
            outcomes = {name for when, name in row["ends"] if when == last_end}
            outcome = outcomes.pop() if len(outcomes) == 1 else None
        elif row["ends"]:
            last_end = max(when for when, _ in row["ends"])
            outcomes = {name for when, name in row["ends"] if when == last_end}
            outcome = outcomes.pop() if len(outcomes) == 1 else None
        complete = latency is not None and outcome is not None and row["bad_timestamps"] == 0
        rows.append({
            "wu": wu, "outcome": outcome, "latency_seconds": latency, "incidents": row["incidents"],
            "pending_gates": row["pending_gates"], "cost_classes": dict(sorted(row["cost_classes"].items())),
            "tokens": row["tokens"] if row["tokens_known"] else None, "confidence": "high" if complete else "low",
        })
    for v in violations:
        v["wu"] = labels[v.pop("wu_key")]
    violations.sort(key=lambda v: (v["index"], v["wu"]))
    return {"receipts": len(receipts), "work_units": rows, "violations": violations, "zero_spend_ok": not violations,
            "by_worker": build_rollups(receipts, "worker"), "by_pr": build_rollups(receipts, "pr"),
            "summary": build_summary(rows)}


def build_summary(rows: list[dict]) -> dict:
    """Overall roll-up derived only from the per-WU rows (no new inputs)."""
    by_outcome: dict[str, int] = {}
    for row in rows:
        name = row["outcome"] if row["outcome"] is not None else "unknown"
        by_outcome[name] = by_outcome.get(name, 0) + 1
    latencies = sorted(r["latency_seconds"] for r in rows if r["latency_seconds"] is not None)
    known = [r["tokens"] for r in rows if r["tokens"] is not None]
    return {
        "work_units": len(rows),
        "by_outcome": dict(sorted(by_outcome.items())),
        "latency_seconds": ({"min": latencies[0], "median": _median(latencies), "max": latencies[-1]}
                            if latencies else None),
        "incidents": sum(r["incidents"] for r in rows),
        "pending_gates": sum(r["pending_gates"] for r in rows),
        "tokens": sum(known) if known else None,
        "low_confidence": sum(1 for r in rows if r["confidence"] != "high"),
    }


def build_rollups(receipts: list, dimension: str) -> list[dict]:
    """Group receipts by ``dimension`` (``worker`` or ``pr``); missing/invalid values form ``unattributed``."""
    groups: dict[str | None, dict] = {}
    for raw in receipts:
        r = raw if isinstance(raw, dict) else {}
        value = r.get(dimension)
        if dimension == "pr" and isinstance(value, int) and not isinstance(value, bool) and value > 0:
            value = f"#{value}"
        key = value if isinstance(value, str) and value else None
        g = groups.setdefault(key, {"events": 0, "incidents": 0, "pending_gates": 0, "cost_classes": {},
                                    "tokens": 0, "tokens_known": False, "bad_timestamps": 0})
        g["events"] += 1
        if parse_time(r.get("at")) is None:
            g["bad_timestamps"] += 1
        event = safe_text(r.get("event"))
        if event in INCIDENT_EVENTS:
            g["incidents"] += 1
        if event in PENDING_EVENTS:
            g["pending_gates"] += 1
        shown = safe_text(r.get("cost_class"), "MISSING")
        g["cost_classes"][shown] = g["cost_classes"].get(shown, 0) + 1
        tokens = r.get("tokens")
        if isinstance(tokens, int) and not isinstance(tokens, bool) and tokens >= 0:
            g["tokens"] += tokens
            g["tokens_known"] = True
    rows = []
    redacted = 0
    for key in sorted(groups, key=lambda k: (k is None, k or "")):
        g = groups[key]
        if key is None:
            name = "unattributed"
        else:
            name = safe_text(key)
            if name == "[redacted]":
                redacted += 1
                name = f"[redacted-{redacted}]"
        rows.append({
            dimension: name, "events": g["events"], "incidents": g["incidents"], "pending_gates": g["pending_gates"],
            "cost_classes": dict(sorted(g["cost_classes"].items())),
            "tokens": g["tokens"] if g["tokens_known"] else None,
            "confidence": "high" if key is not None and g["bad_timestamps"] == 0 else "low",
        })
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only outcome and budget report from receipts.")
    parser.add_argument("--receipts", required=True, help="JSON file containing a list of receipt objects")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args(argv)
    try:
        receipts = json.loads(Path(args.receipts).read_text(encoding="utf-8"))
        allowed, forbidden = load_budget(ROOT)
        report = build_report(receipts, allowed, forbidden)
    except (OSError, ValueError) as exc:
        print(f"outcome-report: {type(exc).__name__}: cannot build report", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        for row in report["work_units"]:
            print(f"{row['wu']}: outcome={row['outcome']} latency_s={row['latency_seconds']} "
                  f"incidents={row['incidents']} pending_gates={row['pending_gates']} confidence={row['confidence']}")
        for dim in ("by_worker", "by_pr"):
            for row in report[dim]:
                label = row["worker" if dim == "by_worker" else "pr"]
                print(f"{dim[3:]} {label}: events={row['events']} incidents={row['incidents']} "
                      f"pending_gates={row['pending_gates']} confidence={row['confidence']}")
        sm = report["summary"]
        print(f"summary: work_units={sm['work_units']} by_outcome={sm['by_outcome']} latency_s={sm['latency_seconds']} "
              f"incidents={sm['incidents']} pending_gates={sm['pending_gates']} low_confidence={sm['low_confidence']}")
        print("zero-spend: " + ("ok" if report["zero_spend_ok"] else f"VIOLATIONS={len(report['violations'])}"))
    return 0 if report["zero_spend_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
