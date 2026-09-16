#!/usr/bin/env python3
"""Repo-native advisory learning plane for OneCompany."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import qualification
from onecompany_lib import CONTROL

KNOWLEDGE_ROOT = CONTROL / "knowledge"
MANIFEST_SCHEMA = "onecompany-knowledge-manifest-v1"
ENTRY_SCHEMA = "onecompany-knowledge-v1"
AUTHORITY = "advisory_only"
STATES = ("candidate", "current", "archived")
MAX_CONTEXT = 8
ID_RE = re.compile(r"^K-[A-Z0-9][A-Z0-9-]{2,127}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
VALIDATION_METHODS = {
    "regression_test",
    "deterministic_reproduction",
    "independent_review",
    "repeated_evidence",
}
ALLOWED_KEYS = {
    "schema",
    "id",
    "title",
    "status",
    "authority",
    "authority_effects",
    "category",
    "summary",
    "problem_pattern",
    "failure_mode",
    "root_cause",
    "prevention_rule",
    "preflight_checks",
    "regression_tests",
    "scope_tags",
    "source_evidence",
    "first_observed_at",
    "last_confirmed_at",
    "observed_count",
    "confidence",
    "supersedes",
    "superseded_by",
    "applicability_notes",
    "bootstrap_safe",
    "validation",
    "archive_reason",
}


class KnowledgeError(ValueError):
    """Raised when knowledge violates the advisory learning contract."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KnowledgeError(f"cannot read knowledge JSON {path}: {exc}") from exc


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise KnowledgeError(f"{field} must be a non-empty string")
    return value


def _string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise KnowledgeError(f"{field} must be a list of non-empty strings")
    if len(value) != len(set(value)):
        raise KnowledgeError(f"{field} must not contain duplicates")
    return value


def load_manifest(root: Path = KNOWLEDGE_ROOT) -> dict[str, Any]:
    manifest = _read_json(root / "manifest.json")
    if not isinstance(manifest, dict) or manifest.get("schema") != MANIFEST_SCHEMA:
        raise KnowledgeError("unsupported knowledge manifest schema")
    if manifest.get("authority") != AUTHORITY or manifest.get("authority_effects") != []:
        raise KnowledgeError("knowledge manifest must remain advisory_only with no authority effects")
    if manifest.get("promotion", {}).get("automatic") is not False:
        raise KnowledgeError("knowledge promotion must not be automatic")
    if manifest.get("promotion", {}).get("knowledge_can_create_hard_gate") is not False:
        raise KnowledgeError("knowledge must not create hard gates")
    max_lessons = manifest.get("max_injected_lessons")
    if not isinstance(max_lessons, int) or isinstance(max_lessons, bool) or not 1 <= max_lessons <= MAX_CONTEXT:
        raise KnowledgeError("knowledge context bound is invalid")
    return manifest


def validate_entry(entry: Any, *, expected_status: str | None = None) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise KnowledgeError("knowledge entry must be an object")
    qualification._reject_sensitive_keys(entry, "knowledge")
    qualification._reject_sensitive_values(entry, "knowledge")
    unknown = sorted(set(entry) - ALLOWED_KEYS)
    if unknown:
        raise KnowledgeError("unsupported knowledge fields: " + ",".join(unknown))
    if entry.get("schema") != ENTRY_SCHEMA:
        raise KnowledgeError("unsupported knowledge entry schema")

    entry_id = _nonempty_string(entry.get("id"), "id")
    if not ID_RE.fullmatch(entry_id):
        raise KnowledgeError("knowledge id must be a normalized K-* identifier")
    status = entry.get("status")
    if status not in STATES:
        raise KnowledgeError("knowledge status must be candidate/current/archived")
    if expected_status is not None and status != expected_status:
        raise KnowledgeError(f"knowledge status/path mismatch for {entry_id}")
    if entry.get("authority") != AUTHORITY or entry.get("authority_effects") != []:
        raise KnowledgeError("knowledge entries must remain advisory_only with no authority effects")

    for field in (
        "title",
        "category",
        "summary",
        "problem_pattern",
        "failure_mode",
        "root_cause",
        "prevention_rule",
        "applicability_notes",
        "confidence",
    ):
        _nonempty_string(entry.get(field), field)
    for field in (
        "preflight_checks",
        "regression_tests",
        "scope_tags",
        "supersedes",
        "superseded_by",
    ):
        _string_list(entry.get(field), field)

    observed = entry.get("observed_count")
    if not isinstance(observed, int) or isinstance(observed, bool) or observed < 1:
        raise KnowledgeError("observed_count must be an integer >= 1")
    if not isinstance(entry.get("bootstrap_safe"), bool):
        raise KnowledgeError("bootstrap_safe must be boolean")
    qualification._parse_time(entry.get("first_observed_at"), "first_observed_at")
    qualification._parse_time(entry.get("last_confirmed_at"), "last_confirmed_at")

    evidence = entry.get("source_evidence")
    if not isinstance(evidence, list) or not evidence:
        raise KnowledgeError("source_evidence must contain provenance")
    for index, item in enumerate(evidence):
        if not isinstance(item, dict) or set(item) != {"kind", "ref", "actor", "severity", "commit"}:
            raise KnowledgeError(f"source_evidence[{index}] has invalid shape")
        for field in ("kind", "ref", "actor", "severity"):
            _nonempty_string(item.get(field), f"source_evidence[{index}].{field}")
        qualification._validate_evidence_ref(str(item["ref"]))
        commit = item.get("commit")
        if commit is not None and (not isinstance(commit, str) or not HEX40.fullmatch(commit)):
            raise KnowledgeError(f"source_evidence[{index}].commit must be null or a 40-char SHA")

    validation = entry.get("validation")
    if not isinstance(validation, dict) or set(validation) != {
        "validated",
        "method",
        "evidence_refs",
        "validated_at",
    }:
        raise KnowledgeError("validation has invalid shape")
    if not isinstance(validation.get("validated"), bool):
        raise KnowledgeError("validation.validated must be boolean")
    refs = _string_list(validation.get("evidence_refs"), "validation.evidence_refs")
    for ref in refs:
        qualification._validate_evidence_ref(ref)

    if status == "current":
        if validation.get("validated") is not True:
            raise KnowledgeError("current knowledge requires validation")
        if validation.get("method") not in VALIDATION_METHODS:
            raise KnowledgeError("current knowledge has unsupported validation method")
        if not refs:
            raise KnowledgeError("current knowledge requires validation evidence")
        qualification._parse_time(validation.get("validated_at"), "validation.validated_at")
        if validation.get("method") == "regression_test" and not entry.get("regression_tests"):
            raise KnowledgeError("regression-test promotion requires regression_tests")
    elif status == "candidate":
        if validation.get("validated") is not False:
            raise KnowledgeError("candidate knowledge cannot already be validated")
        if validation.get("method") is not None or refs or validation.get("validated_at") is not None:
            raise KnowledgeError("candidate validation must remain empty until explicit promotion")
    else:
        _nonempty_string(entry.get("archive_reason"), "archive_reason")

    return entry


def load_entries(
    root: Path = KNOWLEDGE_ROOT,
    *,
    statuses: tuple[str, ...] = STATES,
) -> list[dict[str, Any]]:
    load_manifest(root)
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for status in statuses:
        if status not in STATES:
            raise KnowledgeError(f"unsupported knowledge status {status}")
        directory = root / status
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.json")):
            entry = validate_entry(_read_json(path), expected_status=status)
            if entry["id"] in seen:
                raise KnowledgeError(f"duplicate knowledge id {entry['id']}")
            seen.add(str(entry["id"]))
            entries.append(entry)
    return entries


def fingerprint(entry: dict[str, Any]) -> str:
    material = {
        "category": entry["category"].strip().lower(),
        "problem_pattern": " ".join(entry["problem_pattern"].lower().split()),
        "prevention_rule": " ".join(entry["prevention_rule"].lower().split()),
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def deduplicate_candidates(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge structurally identical candidate claims without losing provenance."""
    merged: dict[str, dict[str, Any]] = {}
    for original in entries:
        entry = validate_entry(copy.deepcopy(original))
        if entry["status"] != "candidate":
            raise KnowledgeError("deduplicate_candidates accepts candidates only")
        key = fingerprint(entry)
        if key not in merged:
            merged[key] = entry
            continue
        target = merged[key]
        existing = {
            json.dumps(item, sort_keys=True, separators=(",", ":"))
            for item in target["source_evidence"]
        }
        for item in entry["source_evidence"]:
            encoded = json.dumps(item, sort_keys=True, separators=(",", ":"))
            if encoded not in existing:
                target["source_evidence"].append(item)
                existing.add(encoded)
        target["observed_count"] += entry["observed_count"]
        target["last_confirmed_at"] = max(
            target["last_confirmed_at"], entry["last_confirmed_at"]
        )
    return sorted(merged.values(), key=lambda item: item["id"])


def detect_conflicts(entries: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Preserve conflicting claims instead of manufacturing consensus."""
    conflicts: list[dict[str, str]] = []
    for index, left in enumerate(entries):
        for right in entries[index + 1 :]:
            if (
                " ".join(left["problem_pattern"].lower().split())
                == " ".join(right["problem_pattern"].lower().split())
                and " ".join(left["prevention_rule"].lower().split())
                != " ".join(right["prevention_rule"].lower().split())
            ):
                conflicts.append({"left": left["id"], "right": right["id"]})
    return conflicts


def promote_candidate(
    entry: dict[str, Any],
    *,
    method: str,
    evidence_refs: list[str],
    validated_at: str,
) -> dict[str, Any]:
    """Return an explicitly validated current lesson; never auto-promote."""
    candidate = validate_entry(copy.deepcopy(entry))
    if candidate["status"] != "candidate":
        raise KnowledgeError("only candidate knowledge can be promoted")
    if method not in VALIDATION_METHODS:
        raise KnowledgeError("unsupported promotion validation method")
    if not evidence_refs:
        raise KnowledgeError("promotion requires validation evidence")
    for ref in evidence_refs:
        qualification._validate_evidence_ref(ref)
    qualification._parse_time(validated_at, "validated_at")
    candidate["status"] = "current"
    candidate["validation"] = {
        "validated": True,
        "method": method,
        "evidence_refs": list(evidence_refs),
        "validated_at": validated_at,
    }
    return validate_entry(candidate)


def archive_entry(
    entry: dict[str, Any],
    *,
    reason: str,
    superseded_by: list[str] | None = None,
) -> dict[str, Any]:
    archived = copy.deepcopy(entry)
    validate_entry(archived)
    archived["status"] = "archived"
    archived["archive_reason"] = _nonempty_string(reason, "archive_reason")
    if superseded_by is not None:
        archived["superseded_by"] = list(superseded_by)
    return validate_entry(archived)


def _terms(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9_-]+", value.lower()) if len(token) > 2}


def retrieve_current(
    *,
    query: str = "",
    tags: list[str] | None = None,
    limit: int = MAX_CONTEXT,
    root: Path = KNOWLEDGE_ROOT,
) -> list[dict[str, Any]]:
    manifest = load_manifest(root)
    bound = min(max(1, int(limit)), int(manifest["max_injected_lessons"]), MAX_CONTEXT)
    wanted_tags = {tag.lower() for tag in (tags or [])}
    wanted_terms = _terms(query)
    scored: list[tuple[int, str, dict[str, Any]]] = []
    for entry in load_entries(root, statuses=("current",)):
        if entry.get("superseded_by"):
            continue
        entry_tags = {tag.lower() for tag in entry["scope_tags"]}
        score = 6 * len(wanted_tags & entry_tags)
        searchable = " ".join(
            [
                entry["title"],
                entry["summary"],
                entry["problem_pattern"],
                entry["prevention_rule"],
                " ".join(entry["scope_tags"]),
            ]
        )
        score += len(wanted_terms & _terms(searchable))
        if wanted_tags or wanted_terms:
            if score <= 0:
                continue
        else:
            score = 1
        scored.append((score, str(entry["id"]), entry))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored[:bound]]


def preflight(
    *,
    query: str = "",
    tags: list[str] | None = None,
    files: list[str] | None = None,
    capability: str | None = None,
    risk: str | None = None,
    limit: int = MAX_CONTEXT,
    root: Path = KNOWLEDGE_ROOT,
) -> dict[str, Any]:
    derived_tags = list(tags or [])
    if capability:
        derived_tags.append(capability)
    if risk:
        derived_tags.append(risk)
    file_terms = " ".join(files or [])
    lessons = retrieve_current(
        query=" ".join(part for part in (query, file_terms) if part),
        tags=derived_tags,
        limit=limit,
        root=root,
    )
    checks: list[str] = []
    regression_tests: list[str] = []
    for lesson in lessons:
        for check in lesson["preflight_checks"]:
            if check not in checks:
                checks.append(check)
        for test in lesson["regression_tests"]:
            if test not in regression_tests:
                regression_tests.append(test)
    return {
        "schema": "onecompany-learning-preflight-v1",
        "authority": AUTHORITY,
        "authority_effects": [],
        "hard_gate_created": False,
        "questions": [
            "Have we seen this failure class before?",
            "What invariant did it violate?",
            "Which analogous call sites or workflows should also be inspected?",
            "Which regression tests should be run or added?",
            "Which exact-state, authority, concurrency, idempotency and failure-contract assumptions must be challenged?",
        ],
        "lesson_ids": [lesson["id"] for lesson in lessons],
        "checks": checks,
        "regression_tests": regression_tests,
    }


def _find_entry_path(entry_id: str, root: Path) -> Path:
    if not ID_RE.fullmatch(entry_id):
        raise KnowledgeError("invalid knowledge id")
    matches = [root / state / f"{entry_id}.json" for state in STATES]
    existing = [path for path in matches if path.exists()]
    if len(existing) != 1:
        raise KnowledgeError(f"knowledge id must resolve to exactly one entry: {entry_id}")
    return existing[0]


def _write_entry(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entry, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    retrieve_p = sub.add_parser("retrieve")
    retrieve_p.add_argument("--query", default="")
    retrieve_p.add_argument("--tag", action="append", default=[])
    retrieve_p.add_argument("--limit", type=int, default=MAX_CONTEXT)
    preflight_p = sub.add_parser("preflight")
    preflight_p.add_argument("--query", default="")
    preflight_p.add_argument("--tag", action="append", default=[])
    preflight_p.add_argument("--file", action="append", default=[])
    preflight_p.add_argument("--capability")
    preflight_p.add_argument("--risk")
    preflight_p.add_argument("--limit", type=int, default=MAX_CONTEXT)
    promote_p = sub.add_parser("promote")
    promote_p.add_argument("--id", required=True)
    promote_p.add_argument("--method", required=True, choices=sorted(VALIDATION_METHODS))
    promote_p.add_argument("--evidence", action="append", required=True)
    promote_p.add_argument("--validated-at", required=True)
    promote_p.add_argument("--write", action="store_true")
    archive_p = sub.add_parser("archive")
    archive_p.add_argument("--id", required=True)
    archive_p.add_argument("--reason", required=True)
    archive_p.add_argument("--superseded-by", action="append", default=[])
    archive_p.add_argument("--write", action="store_true")
    args = parser.parse_args()

    try:
        if args.command == "validate":
            entries = load_entries()
            print(f"KNOWLEDGE VALID: {len(entries)} entries; authority={AUTHORITY}")
            return 0
        if args.command == "retrieve":
            value: Any = retrieve_current(query=args.query, tags=args.tag, limit=args.limit)
        elif args.command == "preflight":
            value = preflight(
                query=args.query,
                tags=args.tag,
                files=args.file,
                capability=args.capability,
                risk=args.risk,
                limit=args.limit,
            )
        elif args.command == "promote":
            source = _find_entry_path(args.id, KNOWLEDGE_ROOT)
            entry = validate_entry(_read_json(source), expected_status="candidate")
            value = promote_candidate(
                entry,
                method=args.method,
                evidence_refs=args.evidence,
                validated_at=args.validated_at,
            )
            if args.write:
                destination = KNOWLEDGE_ROOT / "current" / f"{args.id}.json"
                if destination.exists():
                    raise KnowledgeError("current destination already exists")
                _write_entry(destination, value)
                source.unlink()
        else:
            source = _find_entry_path(args.id, KNOWLEDGE_ROOT)
            entry = validate_entry(_read_json(source))
            value = archive_entry(
                entry,
                reason=args.reason,
                superseded_by=args.superseded_by,
            )
            if args.write:
                destination = KNOWLEDGE_ROOT / "archived" / f"{args.id}.json"
                if destination.exists():
                    raise KnowledgeError("archive destination already exists")
                _write_entry(destination, value)
                source.unlink()
        print(json.dumps(value, indent=2, sort_keys=True))
        return 0
    except (KnowledgeError, qualification.QualificationInputError) as exc:
        print(f"KNOWLEDGE INVALID: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
