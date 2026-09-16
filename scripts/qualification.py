#!/usr/bin/env python3
"""Provider-neutral worker qualification and advisory provenance scoring."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from onecompany_lib import CONTROL

CATALOG = CONTROL / "qualification" / "scenarios.json"
RESULT_SCHEMA = "onecompany-qualification-result-v1"
PROVENANCE_SCHEMA = "onecompany-qualification-provenance-v1"
CATALOG_SCHEMA = "onecompany-qualification-scenarios-v1"
AUTHORITY = "advisory_only"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
SAFE_EVIDENCE_PREFIXES = ("https://", "git:", "repo:", "fixture:")
PROHIBITED_KEY_FRAGMENTS = (
    "credential",
    "secret",
    "raw_prompt",
    "tool_transcript",
    "chain_of_thought",
    "hidden_reasoning",
    "filesystem_path",
    "absolute_path",
)
ALLOWED_RESULT_KEYS = {
    "schema",
    "scenario_id",
    "scenario_sha256",
    "fixture",
    "executor",
    "condition",
    "attempt",
    "retry",
    "started_at",
    "ended_at",
    "actions",
    "decisions",
    "evidence_refs",
    "usage",
}


class QualificationInputError(ValueError):
    """Raised when a qualification record violates the public contract."""


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QualificationInputError(f"cannot read JSON {path}: {exc}") from exc


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def scenario_sha256(scenario: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(scenario)).hexdigest()


def _catalog() -> dict[str, Any]:
    data = _load_json(CATALOG)
    if not isinstance(data, dict):
        raise QualificationInputError("qualification catalog must be an object")
    if data.get("schema") != CATALOG_SCHEMA:
        raise QualificationInputError("unsupported qualification catalog schema")
    if data.get("authority") != AUTHORITY:
        raise QualificationInputError("qualification catalog must remain advisory_only")
    scenarios = data.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise QualificationInputError("qualification catalog must contain scenarios")
    ids: set[str] = set()
    for scenario in scenarios:
        if not isinstance(scenario, dict):
            raise QualificationInputError("qualification scenario must be an object")
        scenario_id = scenario.get("id")
        if not isinstance(scenario_id, str) or not scenario_id:
            raise QualificationInputError("qualification scenario id is required")
        if scenario_id in ids:
            raise QualificationInputError(f"duplicate qualification scenario {scenario_id}")
        ids.add(scenario_id)
        for key in ("forbidden_actions", "required_decisions"):
            values = scenario.get(key)
            if not isinstance(values, list) or not all(
                isinstance(value, str) and value for value in values
            ):
                raise QualificationInputError(
                    f"scenario {scenario_id} has invalid {key}"
                )
    return data


def catalog_entries() -> list[dict[str, str]]:
    data = _catalog()
    return [
        {
            "id": str(scenario["id"]),
            "title": str(scenario.get("title") or ""),
            "category": str(scenario.get("category") or ""),
            "condition": str(scenario.get("condition") or ""),
            "sha256": scenario_sha256(scenario),
        }
        for scenario in data["scenarios"]
    ]


def _scenario_by_id(scenario_id: str) -> dict[str, Any]:
    for scenario in _catalog()["scenarios"]:
        if scenario.get("id") == scenario_id:
            return scenario
    raise QualificationInputError(f"unknown qualification scenario {scenario_id}")


def _reject_sensitive_keys(value: Any, path: str = "result") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).lower()
            if any(fragment in normalized for fragment in PROHIBITED_KEY_FRAGMENTS):
                raise QualificationInputError(
                    f"privacy-sensitive provenance field is forbidden: {path}.{key}"
                )
            _reject_sensitive_keys(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_sensitive_keys(nested, f"{path}[{index}]")


def _require_string(mapping: dict[str, Any], key: str, context: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise QualificationInputError(f"{context}.{key} must be a non-empty string")
    return value


def _string_list(value: Any, field: str, *, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise QualificationInputError(f"{field} must be a list of non-empty strings")
    if nonempty and not value:
        raise QualificationInputError(f"{field} must not be empty")
    if len(value) != len(set(value)):
        raise QualificationInputError(f"{field} must not contain duplicates")
    return value


def _parse_time(value: Any, field: str) -> dt.datetime:
    if not isinstance(value, str) or not value:
        raise QualificationInputError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise QualificationInputError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise QualificationInputError(f"{field} must include a timezone")
    return parsed


def _validate_result(result: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(result, dict):
        raise QualificationInputError("qualification result must be an object")
    _reject_sensitive_keys(result)
    unknown = sorted(set(result) - ALLOWED_RESULT_KEYS)
    if unknown:
        raise QualificationInputError(
            "unsupported qualification result fields: " + ",".join(unknown)
        )
    if result.get("schema") != RESULT_SCHEMA:
        raise QualificationInputError("unsupported qualification result schema")

    scenario_id = _require_string(result, "scenario_id", "result")
    scenario = _scenario_by_id(scenario_id)
    expected_hash = scenario_sha256(scenario)
    if result.get("scenario_sha256") != expected_hash:
        raise QualificationInputError("scenario hash does not match the canonical catalog")
    if result.get("condition") != scenario.get("condition"):
        raise QualificationInputError("result condition does not match the scenario")

    fixture = result.get("fixture")
    if not isinstance(fixture, dict):
        raise QualificationInputError("result.fixture must be an object")
    if set(fixture) != {"repository", "base_commit", "fixture_id"}:
        raise QualificationInputError(
            "result.fixture must contain repository, base_commit and fixture_id only"
        )
    _require_string(fixture, "repository", "result.fixture")
    base_commit = _require_string(fixture, "base_commit", "result.fixture")
    if not HEX40.fullmatch(base_commit):
        raise QualificationInputError("result.fixture.base_commit must be a 40-char SHA")
    _require_string(fixture, "fixture_id", "result.fixture")

    executor = result.get("executor")
    if not isinstance(executor, dict):
        raise QualificationInputError("result.executor must be an object")
    expected_executor_keys = {"actor", "mechanism", "model_label", "harness_version"}
    if set(executor) != expected_executor_keys:
        raise QualificationInputError(
            "result.executor must contain actor, mechanism, model_label and harness_version only"
        )
    for key in sorted(expected_executor_keys):
        _require_string(executor, key, "result.executor")

    attempt = result.get("attempt")
    retry = result.get("retry")
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise QualificationInputError("result.attempt must be an integer >= 1")
    if not isinstance(retry, int) or isinstance(retry, bool) or retry < 0:
        raise QualificationInputError("result.retry must be an integer >= 0")

    started = _parse_time(result.get("started_at"), "result.started_at")
    ended = _parse_time(result.get("ended_at"), "result.ended_at")
    if ended < started:
        raise QualificationInputError("result.ended_at cannot precede started_at")

    _string_list(result.get("actions"), "result.actions")
    _string_list(result.get("decisions"), "result.decisions")
    evidence_refs = _string_list(
        result.get("evidence_refs"),
        "result.evidence_refs",
        nonempty=True,
    )
    for ref in evidence_refs:
        if not ref.startswith(SAFE_EVIDENCE_PREFIXES):
            raise QualificationInputError(
                "evidence refs must be repository/Git/fixture/HTTPS references, not local paths"
            )

    usage = result.get("usage")
    if not isinstance(usage, dict):
        raise QualificationInputError("result.usage must be an object")
    if set(usage) != {"input_tokens", "output_tokens", "source", "complete"}:
        raise QualificationInputError(
            "result.usage must contain input_tokens, output_tokens, source and complete only"
        )
    _require_string(usage, "source", "result.usage")
    if not isinstance(usage.get("complete"), bool):
        raise QualificationInputError("result.usage.complete must be boolean")
    for key in ("input_tokens", "output_tokens"):
        value = usage.get(key)
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < 0
        ):
            raise QualificationInputError(
                f"result.usage.{key} must be null or an integer >= 0"
            )

    return result, scenario


def evaluate(result: Any) -> tuple[int, dict[str, Any]]:
    record, scenario = _validate_result(result)
    actions = set(record["actions"])
    decisions = set(record["decisions"])
    forbidden = sorted(actions & set(scenario["forbidden_actions"]))
    missing = sorted(set(scenario["required_decisions"]) - decisions)
    failures: list[str] = []
    failures.extend(f"forbidden_action:{value}" for value in forbidden)
    failures.extend(f"missing_decision:{value}" for value in missing)
    verdict = "PASS" if not failures else "FAIL"

    started = _parse_time(record["started_at"], "result.started_at")
    ended = _parse_time(record["ended_at"], "result.ended_at")
    provenance = {
        "schema": PROVENANCE_SCHEMA,
        "authority": AUTHORITY,
        "scenario": {
            "id": scenario["id"],
            "sha256": scenario_sha256(scenario),
            "category": scenario.get("category"),
            "condition": scenario.get("condition"),
        },
        "fixture": record["fixture"],
        "executor": record["executor"],
        "execution": {
            "started_at": record["started_at"],
            "ended_at": record["ended_at"],
            "duration_ms": int((ended - started).total_seconds() * 1000),
            "attempt": record["attempt"],
            "retry": record["retry"],
        },
        "result": {
            "verdict": verdict,
            "failures": failures,
        },
        "evidence_refs": record["evidence_refs"],
        "usage": record["usage"],
        "authority_effects": [],
    }
    return (0 if verdict == "PASS" else 1), provenance


def _write_or_print(value: Any, output: Path | None) -> None:
    text = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if output is None:
        print(text, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    catalog_p = sub.add_parser("catalog")
    catalog_p.add_argument("--json", action="store_true")
    evaluate_p = sub.add_parser("evaluate")
    evaluate_p.add_argument("--result", required=True, type=Path)
    evaluate_p.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        if args.command == "catalog":
            entries = catalog_entries()
            if args.json:
                _write_or_print(entries, None)
            else:
                for entry in entries:
                    print(
                        f"{entry['id']} {entry['sha256']} "
                        f"{entry['category']} {entry['condition']}"
                    )
            return 0
        result = _load_json(args.result)
        exit_code, provenance = evaluate(result)
        _write_or_print(provenance, args.output)
        return exit_code
    except QualificationInputError as exc:
        print(f"QUALIFICATION INVALID: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
