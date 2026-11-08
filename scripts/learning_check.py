#!/usr/bin/env python3
"""Deterministic, read-only learning-loop check (OC-P1-11 slice 1, #469).

Input: ``{"revision": 40-hex, "lessons": [{"id", "status": validated|retired|falsified,
"source_defects": [defect ids], "evidence_refs": [str]}], "defects": [{"id", "held_out": bool,
"lesson": lesson id or null, "recurred": bool}]}``.
A validated lesson needs evidence; a held-out benchmark defect must never be a lesson source
(leakage); a validated lesson credited on a held-out defect that recurred is falsified and must be
retired; a retired or falsified lesson must not be credited (stale memory); and improvement is only
claimed when the held-out recurrence rate with a validated lesson is strictly below the rate without
one. No network, no writes, no clock.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HEX40 = re.compile(r"[0-9a-fA-F]{40}")
STATUSES = {"validated", "retired", "falsified"}


def _name(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _list(data: dict, key: str) -> list:
    value = data.get(key)
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    return value


def _unique_ids(items: list, label: str) -> None:
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or not _name(item.get("id")):
            raise ValueError(f"{label} needs a non-empty string id")
        if item["id"] in seen:
            raise ValueError(f"duplicate {label} id: {item['id']}")
        seen.add(item["id"])


def load_report(path: Path) -> dict:
    """Return the validated report; raise ValueError on anything malformed."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"report unreadable: {path.name} ({exc.__class__.__name__})") from exc
    if not isinstance(data, dict):
        raise ValueError("report is not an object")
    if not isinstance(data.get("revision"), str) or not HEX40.fullmatch(data["revision"]):
        raise ValueError("report needs a 40-hex revision")
    lessons, defects = _list(data, "lessons"), _list(data, "defects")
    _unique_ids(lessons, "lesson")
    _unique_ids(defects, "defect")
    known = {l["id"] for l in lessons}
    for l in lessons:
        if not isinstance(l.get("status"), str) or l["status"] not in STATUSES:
            raise ValueError(f"{l['id']} has unknown status")
        for field in ("source_defects", "evidence_refs"):
            value = l.get(field)
            if not isinstance(value, list) or not all(_name(v) for v in value):
                raise ValueError(f"{l['id']} {field} must be a list of non-empty strings")
    for d in defects:
        if not isinstance(d.get("held_out"), bool) or not isinstance(d.get("recurred"), bool):
            raise ValueError(f"{d['id']} held_out and recurred must be booleans")
        ref = d.setdefault("lesson", None)
        if ref is not None and (not isinstance(ref, str) or ref not in known):
            raise ValueError(f"{d['id']} references an unknown lesson")
    return data


def evaluate(report: dict) -> dict:
    problems: list[str] = []
    lessons = {l["id"]: l for l in report["lessons"]}
    held = [d for d in report["defects"] if d["held_out"]]
    held_ids = {d["id"] for d in held}
    for lid, l in sorted(lessons.items()):
        if l["status"] == "validated" and not l["evidence_refs"]:
            problems.append(f"NO_EVIDENCE {lid} validated lesson has no evidence_refs")
        for did in sorted(set(l["source_defects"]) & held_ids):
            problems.append(f"LEAKED_BENCHMARK {lid} learned from held-out defect {did}")
    for d in sorted(report["defects"], key=lambda d: d["id"]):
        lesson = lessons.get(d["lesson"]) if d["lesson"] is not None else None
        if lesson is None:
            continue
        if lesson["status"] != "validated":
            problems.append(f"STALE_LESSON_CREDITED {d['id']} credits {lesson['status']} lesson {lesson['id']}")
        elif d["held_out"] and d["recurred"]:
            problems.append(f"VALIDATED_LESSON_RECURRED {d['id']} recurred despite {lesson['id']}")
    if not held:
        problems.append("NO_HELD_OUT_BENCHMARK no held-out defects")
    else:
        def credited(d: dict) -> bool:
            return d["lesson"] is not None and lessons[d["lesson"]]["status"] == "validated"
        with_l = [d for d in held if credited(d)]
        without = [d for d in held if not credited(d)]
        if not with_l or not without:
            problems.append("IMPROVEMENT_UNMEASURED needs held-out defects both with and without a validated lesson")
        else:
            r_with = sum(d["recurred"] for d in with_l)
            r_without = sum(d["recurred"] for d in without)
            if r_with * len(without) >= r_without * len(with_l):
                problems.append(f"NO_IMPROVEMENT recurrence {r_with}/{len(with_l)} with lesson vs "
                                f"{r_without}/{len(without)} without")
    return {"lessons": len(lessons), "held_out": len(held), "problems": problems}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only learning-loop check.")
    parser.add_argument("report", help="learning report JSON file")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args(argv)
    try:
        result = evaluate(load_report(Path(args.report)))
    except ValueError as exc:
        print(f"learning-check: UNABLE TO VERIFY ({exc})", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"learning-check: {result['lessons']} lessons, {result['held_out']} held-out defects, "
              f"{len(result['problems'])} problems")
        for item in result["problems"]:
            print(f"  {item}")
    return 1 if result["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
