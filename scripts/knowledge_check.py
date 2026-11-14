#!/usr/bin/env python3
"""Deterministic, read-only knowledge store check (OC-P1-07 slices 1-2, #459, #487).

Loads the lesson store through ``knowledge.load_entries`` and reports lessons that must not be trusted
as injected context: instruction-override / authority / exfiltration language in free text of candidate
and current lessons, current lessons that are already retracted (``superseded_by`` set), and
supersession links to unknown ids, ``repo:`` provenance that does not resolve to a file in the checkout
(MISSING_EVIDENCE_FILE) and regression-validated current lessons that cite no existing test file
(UNGROUNDED_REGRESSION; slice 2, fabricated-proof guard). Archived lessons are never injected and are not scanned. No
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
LIST_TEXT_FIELDS = ("preflight_checks", "regression_tests")
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


def _repo_refs(entry: dict):
    """Yield (field, path) for every ``repo:`` provenance reference of a lesson."""
    for item in entry.get("source_evidence") or []:
        ref = item.get("ref") if isinstance(item, dict) else None
        if isinstance(ref, str) and ref.startswith("repo:"):
            yield "source_evidence", ref[5:]
    for ref in (entry.get("validation") or {}).get("evidence_refs") or []:
        if isinstance(ref, str) and ref.startswith("repo:"):
            yield "validation", ref[5:]


def _file_exists(repo_root: Path, rel: str) -> bool:
    """True only for a regular file that stays inside the checkout (no traversal, no symlink escape)."""
    if not rel or rel.startswith("/") or ".." in Path(rel).parts:
        return False
    try:
        base = repo_root.resolve()
        target = (base / rel).resolve()
        return target.is_file() and base in target.parents
    except (OSError, RuntimeError):  # RuntimeError: symlink loop on Python < 3.13
        return False


def _is_test_file(rel: str) -> bool:
    """A regression-test citation must be a test_*.py file under a tests/ or selftest/ directory."""
    path = Path(rel)
    return path.name.startswith("test_") and path.suffix == ".py" and any(
        part in ("tests", "selftest") for part in path.parts[:-1])


def evaluate(entries: list[dict], repo_root: Path | None = None) -> dict:
    known = {e["id"] for e in entries}
    problems: list[str] = []
    for entry in sorted(entries, key=lambda e: e["id"]):
        eid, status = entry["id"], entry["status"]
        if status in ("candidate", "current"):
            hit_fields = sorted({f for f, t in _texts(entry) if any(p.search(_normalise(t)) for p in COMPILED)})
            problems.extend(f"PROMPT_INJECTION {eid} {f}" for f in hit_fields)
        if status == "current" and entry.get("superseded_by"):
            problems.append(f"RETRACTED_STILL_CURRENT {eid}")
        if repo_root is not None and status in ("candidate", "current"):
            for field, rel in sorted(set(_repo_refs(entry))):
                if not _file_exists(repo_root, rel):
                    problems.append(f"MISSING_EVIDENCE_FILE {eid} {field} repo:{rel}")
            if status == "current" and (entry.get("validation") or {}).get("method") == "regression_test":
                tests = [rel for field, rel in _repo_refs(entry)
                         if field == "validation" and _is_test_file(rel) and _file_exists(repo_root, rel)]
                if not tests:
                    problems.append(f"UNGROUNDED_REGRESSION {eid} no existing repo test file (test_*.py under tests/ or selftest/) cited as validation evidence")
        for field in ("supersedes", "superseded_by"):
            for ref in sorted(set(entry.get(field) or [])):
                if ref not in known:
                    problems.append(f"DANGLING_SUPERSESSION {eid} {ref}")
    return {"lessons": len(entries), "problems": problems}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only knowledge store check.")
    parser.add_argument("--root", help="knowledge store root (default: repository store)")
    parser.add_argument("--repo-root", help="checkout that repo: evidence refs resolve against (default: this checkout)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args(argv)
    try:
        root = Path(args.root) if args.root else knowledge.KNOWLEDGE_ROOT
        # load_entries() would converge interrupted transitions (writes); this check is read-only.
        tx_root = root / ".transactions"
        if tx_root.is_symlink() or (tx_root.exists() and (not tx_root.is_dir() or any(tx_root.iterdir()))):
            raise knowledge.KnowledgeError("pending lifecycle transactions; recovery required before checking")
        repo_root = Path(args.repo_root) if args.repo_root else Path(__file__).resolve().parent.parent
        result = evaluate(knowledge.load_entries(root), repo_root)
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
