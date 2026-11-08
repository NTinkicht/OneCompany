#!/usr/bin/env python3
"""Deterministic, read-only knowledge store check (OC-P1-07 slice 1, #459).

Loads the lesson store through ``knowledge.load_entries`` and reports lessons that must not be trusted
as injected context: instruction-override / authority / exfiltration language in free text of candidate
and current lessons, current lessons that are already retracted (``superseded_by`` set), and
supersession links to unknown ids. Archived lessons are never injected and are not scanned. No
network, no writes, no clock. Invalid store: exit 2.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

import knowledge

TEXT_FIELDS = ("title", "summary", "problem_pattern", "failure_mode", "root_cause",
               "prevention_rule", "applicability_notes")
LIST_TEXT_FIELDS = ("preflight_checks",)
PATTERNS = (
    r"ignore (all |any )?(the )?(previous|prior|above|earlier) (instructions|rules|guidance)",
    r"disregard (all |any )?(the )?(previous|prior|above|earlier|your) (instructions|rules|guidance)",
    r"(forget|override|bypass) (your|the|all) (instructions|rules|policy|policies|guardrails)",
    r"you (must|should) (now )?(approve|merge|deploy|force[- ]push)",
    r"(approve|merge) (this|the|any) (pr|pull request|change)s? without",
    r"(disable|turn off|skip) (the )?(emergency stop|review|ci|tests|branch protection)",
    r"(reveal|print|send|exfiltrate|leak) (the |your |any )?(secrets?|tokens?|credentials?|system prompt)",
    r"(system|developer) prompt",
    r"new instructions?:",
    r"act as (an? )?(admin|owner|maintainer)",
)
COMPILED = tuple(re.compile(p) for p in PATTERNS)


def _normalise(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[\s_*`]+", " ", folded)


def _texts(entry: dict):
    for field in TEXT_FIELDS:
        value = entry.get(field)
        if isinstance(value, str):
            yield field, value
    for field in LIST_TEXT_FIELDS:
        for item in entry.get(field) or []:
            if isinstance(item, str):
                yield field, item


def evaluate(entries: list[dict]) -> dict:
    known = {e["id"] for e in entries}
    problems: list[str] = []
    for entry in sorted(entries, key=lambda e: e["id"]):
        eid, status = entry["id"], entry["status"]
        if status in ("candidate", "current"):
            hit_fields = sorted({f for f, t in _texts(entry) if any(p.search(_normalise(t)) for p in COMPILED)})
            problems.extend(f"PROMPT_INJECTION {eid} {f}" for f in hit_fields)
        if status == "current" and entry.get("superseded_by"):
            problems.append(f"RETRACTED_STILL_CURRENT {eid}")
        for field in ("supersedes", "superseded_by"):
            for ref in sorted(set(entry.get(field) or [])):
                if ref not in known:
                    problems.append(f"DANGLING_SUPERSESSION {eid} {ref}")
    return {"lessons": len(entries), "problems": problems}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only knowledge store check.")
    parser.add_argument("--root", help="knowledge store root (default: repository store)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args(argv)
    try:
        root = Path(args.root) if args.root else knowledge.KNOWLEDGE_ROOT
        result = evaluate(knowledge.load_entries(root))
    except (knowledge.KnowledgeError, OSError, ValueError) as exc:
        print(f"knowledge-check: UNABLE TO VERIFY ({exc.__class__.__name__}: {exc})", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"knowledge-check: {result['lessons']} lessons, {len(result['problems'])} problems")
        for item in result["problems"]:
            print(f"  {item}")
    return 1 if result["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
