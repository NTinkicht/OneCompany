#!/usr/bin/env python3
"""Validate an untrusted, planner-proposed WU decomposition against an owner brief.

Local and offline: no network, provider call, credential read or spend. The plan
is data only; it is parsed and validated, never executed or followed. Accepted
plans are emitted as ``PROPOSED`` work units for one-at-a-time admission through
the approval path. This command admits nothing, creates no lease, RunKey,
dispatch or merge decision, and never edits any file.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any

from onecompany_lib import CONTROL
from planning_lib import (DependencyCycleError, by_id, critical_path,
                          dependency_closure, rank_work, scopes_overlap)
from scope_guard import _normalize as canonical_scope

SCHEMA = "onecompany.workplan.v1"
RESULT_SCHEMA = "onecompany.workplan-verdict.v1"
MAX_BYTES = 262_144
MAX_WUS = 12
MAX_LINES = 400
MAX_SCOPES = 20
MAX_LIST = 20
WU_ID = re.compile(r"WU[0-9A-Za-z._-]{1,80}\Z")
RISKS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
BRIEF_KEYS = ("audience", "problem", "outcome", "first_feature", "constraints")
PLAN_KEYS = {"schema", "work_units"}
WU_KEYS = {"id", "title", "requirement_ids", "acceptance_criteria", "write_scope",
           "risk_class", "tests", "estimate", "dependencies"}
CRITERION_KEYS = {"id", "text", "brief_ref"}
# Mirrors the protected paths in the standing engineering rules; a plan may never
# route a work unit into the control plane or the governance files.
PROTECTED = (".github", "CODEOWNERS", ".onecompany/config.json", ".onecompany/budget.json",
             "PRODUCT.md", "AGENTS.md", "CLAUDE.md", "GEMINI.md", "GROK.md", "VIBE.md",
             "coordination", ".l5", ".claude", ".vibe")
FORBIDDEN_WORK = re.compile(
    r"\b(spend\w*|paid|pay(?:ing|ment|ments)?|billing|billable|purchas\w*|"
    r"credential\w*|secret\w*|password\w*|api[ _-]?keys?|tokens?|private[ _-]keys?|"
    r"deploy\w*|production|prod|go[ -]live|release[ -]to)\b", re.I)
GOVERNANCE = CONTROL / "governance.json"
CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


def read_bounded(path: Path) -> dict:
    """Read one regular file without following links and parse a JSON object."""
    if not getattr(os, "O_NOFOLLOW", 0) or not getattr(os, "O_NONBLOCK", 0):
        raise ValueError("SECURE_READ_UNAVAILABLE")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        raise ValueError("INPUT_UNREADABLE") from None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("INPUT_NOT_REGULAR_FILE")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(MAX_BYTES + 1)
    finally:
        os.close(fd)
    if len(raw) > MAX_BYTES:
        raise ValueError("INPUT_TOO_LARGE")

    def no_duplicates(pairs: list[tuple[str, Any]]) -> dict:
        out: dict[str, Any] = {}
        for key, value in pairs:
            if key in out:
                raise ValueError("INPUT_DUPLICATE_KEY")
            out[key] = value
        return out

    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=no_duplicates)
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise ValueError("INPUT_NOT_JSON") from None
    if not isinstance(data, dict):
        raise ValueError("INPUT_NOT_OBJECT")
    return data


def brief_refs(brief: dict) -> dict[str, str]:
    """Return the owner-authored statements a criterion may trace to."""
    answers = brief.get("answers")
    if not isinstance(answers, dict):
        return {}
    return {f"answers.{k}": answers[k].strip() for k in BRIEF_KEYS
            if isinstance(answers.get(k), str) and answers[k].strip()}


def clean_text(value: Any, limit: int) -> bool:
    return (isinstance(value, str) and value.strip() != "" and len(value) <= limit
            and not CONTROL_CHARS.search(value))


def normalize_scope(item: Any) -> str | None:
    if not isinstance(item, str):
        return None
    text = item.strip()
    # Same canonical form as scripts/scope_guard.py; anything it would rewrite
    # (src//a, src/./a, ./a, a/, leading "/") or reject is refused here, so the
    # validator and the runtime scope guard can never disagree on a scope.
    if (not text or len(text) > 200 or "\\" in text or CONTROL_CHARS.search(text)
            or canonical_scope(text) != text or text in {"*", "**", "**/*"}):
        return None
    return text


_PROTECTED_CACHE: tuple[str, ...] | None = None


def protected_paths() -> tuple[str, ...]:
    """Static families plus the trusted governance policy; unreadable policy fails closed."""
    global _PROTECTED_CACHE
    if _PROTECTED_CACHE is None:
        try:
            control = json.loads(GOVERNANCE.read_text(encoding="utf-8"))["control_plane"]
            derived = [p for key in ("protected_paths", "always_human_paths")
                       for p in control[key] if isinstance(p, str) and p.strip()]
            if not derived:
                raise ValueError("empty")
        except (OSError, ValueError, KeyError, TypeError):
            # Cannot establish the trusted policy: protect the whole tree.
            derived = ["**"]
        _PROTECTED_CACHE = tuple(dict.fromkeys([*PROTECTED, *derived]))
    return _PROTECTED_CACHE


def touches_protected(scope: str) -> bool:
    return any(scopes_overlap(scope, path) for path in protected_paths())


def check_unit(unit: Any, refs: dict[str, str], add) -> dict | None:
    """Validate one WU's own fields; return a normalized copy or None."""
    if not isinstance(unit, dict):
        add("WU_NOT_OBJECT", "?", "work unit is not an object")
        return None
    uid = unit.get("id")
    if not isinstance(uid, str) or not WU_ID.fullmatch(uid):
        add("WU_ID_INVALID", str(uid)[:40], "id must match WU[0-9A-Za-z._-]{1,80}")
        return None
    bad = False

    def fail(code: str, detail: str) -> None:
        nonlocal bad
        bad = True
        add(code, uid, detail)

    extra = set(unit) - WU_KEYS
    if extra:
        fail("WU_UNKNOWN_FIELDS", ",".join(sorted(str(k) for k in extra))[:100])
    if not clean_text(unit.get("title"), 120):
        fail("TITLE_INVALID", "title must be 1-120 chars without control characters")
    reqs = unit.get("requirement_ids")
    if (not isinstance(reqs, list) or not reqs or len(reqs) > MAX_LIST
            or any(not clean_text(r, 80) for r in reqs)):
        fail("REQUIREMENT_IDS_INVALID", "at least one requirement id is required")
    criteria = unit.get("acceptance_criteria")
    texts: list[str] = []
    if not isinstance(criteria, list) or not criteria or len(criteria) > MAX_LIST:
        fail("NO_ACCEPTANCE_CRITERIA", "at least one acceptance criterion is required")
    else:
        seen: set[str] = set()
        for crit in criteria:
            if (not isinstance(crit, dict) or set(crit) != CRITERION_KEYS
                    or not clean_text(crit.get("id"), 80) or not clean_text(crit.get("text"), 400)
                    or crit["id"] in seen):
                fail("CRITERION_INVALID", "criterion needs unique id, text and brief_ref only")
                continue
            seen.add(crit["id"])
            if not isinstance(crit.get("brief_ref"), str) or crit["brief_ref"] not in refs:
                fail("CRITERION_NOT_TRACEABLE",
                     f"{crit['id']}: brief_ref must name an owner-answered brief field")
            texts.append(crit["text"])
    tests = unit.get("tests")
    if (not isinstance(tests, list) or not tests or len(tests) > MAX_LIST
            or any(not clean_text(t, 200) for t in tests)):
        fail("NO_TESTS", "at least one named test is required")
    scopes = unit.get("write_scope")
    norm: list[str] = []
    if not isinstance(scopes, list) or not scopes or len(scopes) > MAX_SCOPES:
        fail("WRITE_SCOPE_INVALID", "1-20 exact scoped write globs are required")
    else:
        for item in scopes:
            scope = normalize_scope(item)
            if scope is None or scope in norm:
                fail("WRITE_SCOPE_INVALID", f"unscoped, unsafe or duplicate scope: {str(item)[:60]}")
            else:
                norm.append(scope)
                if touches_protected(scope):
                    fail("PROTECTED_PATH", f"scope touches a protected path: {scope}")
    if unit.get("risk_class") not in RISKS:
        fail("RISK_CLASS_INVALID", "risk_class must be one of " + "/".join(RISKS))
    estimate = unit.get("estimate")
    lines = estimate.get("lines") if isinstance(estimate, dict) else None
    if (not isinstance(estimate, dict) or set(estimate) != {"lines"}
            or isinstance(lines, bool) or not isinstance(lines, int) or lines < 1):
        fail("ESTIMATE_INVALID", "estimate must be {\"lines\": positive integer}")
    elif lines > MAX_LINES:
        fail("ESTIMATE_TOO_LARGE", f"{lines} lines exceeds {MAX_LINES}")
    deps = unit.get("dependencies")
    if (not isinstance(deps, list) or len(deps) > MAX_LIST
            or any(not isinstance(d, str) for d in deps) or len(set(deps)) != len(deps)):
        fail("DEPENDENCIES_INVALID", "dependencies must be a list of unique ids")
    # Planner prose is untrusted data: it is only ever pattern-checked, never obeyed.
    haystack = " ".join([str(unit.get("title", "")), *texts,
                         *map(str, scopes if isinstance(scopes, list) else []),
                         *map(str, tests if isinstance(tests, list) else [])])
    if FORBIDDEN_WORK.search(haystack):
        fail("FORBIDDEN_WORK", "involves spend, credentials, deployment or production")
    if bad:
        return None
    return {"id": uid, "title": unit["title"].strip(), "requirement_ids": list(reqs),
            "acceptance_criteria": [dict(c) for c in criteria], "write_scope": norm,
            "risk_class": unit["risk_class"], "tests": list(tests), "lines": lines,
            "dependencies": list(deps)}


def find_cycle(graph: dict[str, list[str]]) -> list[str] | None:
    state: dict[str, int] = {}
    for start in sorted(graph):
        stack = [(start, iter(sorted(graph[start])))]
        state[start] = 1
        while stack:
            node, it = stack[-1]
            for nxt in it:
                if state.get(nxt) == 1:
                    return [node, nxt]
                if nxt not in state:
                    state[nxt] = 1
                    stack.append((nxt, iter(sorted(graph[nxt]))))
                    break
            else:
                state[node] = 2
                stack.pop()
    return None


def order(units: list[dict]) -> list[str]:
    """Deterministic dependency-respecting order using the existing ranking."""
    ranked = [u["id"] for u in rank_work(units, {})]
    placed: list[str] = []
    while len(placed) < len(ranked):
        for uid in ranked:
            if uid not in placed and all(d in placed for d in by_id(units)[uid]["dependencies"]):
                placed.append(uid)
                break
        else:  # unreachable once cycles are refused
            raise DependencyCycleError("unorderable")
    return placed


def validate(plan: dict, brief: dict) -> dict:
    """Return a deterministic verdict; never raises on hostile plan content."""
    reasons: list[dict] = []

    def add(code: str, wu: str, detail: str) -> None:
        reasons.append({"code": code, "work_unit": wu, "detail": detail})

    refs = brief_refs(brief)
    if not refs:
        add("BRIEF_UNUSABLE", "-", "brief has no owner-answered fields to trace to")
    if plan.get("schema") != SCHEMA or set(plan) != PLAN_KEYS:
        add("PLAN_SCHEMA_INVALID", "-", f"plan must be exactly {sorted(PLAN_KEYS)} with schema {SCHEMA}")
    units = plan.get("work_units")
    if not isinstance(units, list) or not units:
        add("PLAN_EMPTY", "-", "work_units must be a non-empty list")
        units = []
    if len(units) > MAX_WUS:
        add("TOO_MANY_WORK_UNITS", "-", f"{len(units)} work units exceeds {MAX_WUS}")
        units = units[:MAX_WUS]
    good: list[dict] = []
    ids: set[str] = set()
    for raw in units:
        unit = check_unit(raw, refs, add)
        if unit is None:
            continue
        if unit["id"] in ids:
            add("DUPLICATE_ID", unit["id"], "work unit ids must be unique")
            continue
        ids.add(unit["id"])
        good.append(unit)
    for unit in good:
        for dep in unit["dependencies"]:
            if dep == unit["id"] or dep not in ids:
                add("DEPENDENCY_INVALID", unit["id"], f"unknown or self dependency: {dep[:60]}")
    cycle = find_cycle({u["id"]: [d for d in u["dependencies"] if d in ids] for u in good})
    if cycle:
        add("DEPENDENCY_CYCLE", cycle[0], f"cycle through {cycle[0]} and {cycle[1]}")
    if not any(r["code"] in {"DEPENDENCY_INVALID", "DEPENDENCY_CYCLE"} for r in reasons):
        wmap = by_id(good)
        for i, left in enumerate(good):
            for right in good[i + 1:]:
                if not any(scopes_overlap(a, b) for a in left["write_scope"] for b in right["write_scope"]):
                    continue
                if (right["id"] not in dependency_closure(wmap, left["id"])
                        and left["id"] not in dependency_closure(wmap, right["id"])):
                    add("SCOPE_OVERLAP_UNSERIALIZED", left["id"],
                        f"overlaps {right['id']} without a dependency between them")
    reasons.sort(key=lambda r: (r["code"], r["work_unit"], r["detail"]))
    result: dict[str, Any] = {
        "schema": RESULT_SCHEMA, "verdict": "REFUSED" if reasons else "ACCEPTED",
        "authorization": "NOT_GRANTED", "admitted": [], "reasons": reasons,
        "proposals": [], "critical_path": None, "next_order": [],
    }
    if reasons:
        return result
    work = [{"id": u["id"], "title": u["title"], "work_kind": "DELIVERY", "status": "PROPOSED",
             "priority": 100, "dependencies": u["dependencies"], "risk_class": u["risk_class"],
             "requirement_ids": u["requirement_ids"], "write_scope": u["write_scope"],
             "parallelism": "disjoint_only", "tests": u["tests"],
             "acceptance_criteria": u["acceptance_criteria"],
             "estimate": {"job_size": max(u["lines"] / 100.0, 0.1), "lines": u["lines"]}}
            for u in good]
    result["proposals"] = sorted(work, key=lambda w: w["id"])
    result["critical_path"] = critical_path(work)
    result["next_order"] = order(work)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate an untrusted work plan; admits nothing")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--brief", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        plan, brief = read_bounded(args.input), read_bounded(args.brief)
    except ValueError as exc:
        print(json.dumps({"schema": RESULT_SCHEMA, "verdict": "REFUSED", "authorization": "NOT_GRANTED",
                          "admitted": [], "reasons": [{"code": str(exc), "work_unit": "-", "detail": "unreadable input"}],
                          "proposals": [], "critical_path": None, "next_order": []}, sort_keys=True))
        return 2
    result = validate(plan, brief)
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0 if result["verdict"] == "ACCEPTED" else 1


if __name__ == "__main__":
    sys.exit(main())
