#!/usr/bin/env python3
"""Provider-neutral worker qualification and advisory provenance scoring."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from onecompany_lib import CONTROL, ROOT

CATALOG = CONTROL / "qualification" / "scenarios.json"
OUTPUT_ROOT = ROOT / ".onecompany-evidence" / "qualification"
RESULT_SCHEMA = "onecompany-qualification-result-v1"
PROVENANCE_SCHEMA = "onecompany-qualification-provenance-v1"
CATALOG_SCHEMA = "onecompany-qualification-scenarios-v1"
AUTHORITY = "advisory_only"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+\-]{0,127}$")
SAFE_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SAFE_EVIDENCE_TOKEN = re.compile(r"^[A-Za-z0-9._:@/+\-]{1,512}$")
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
SECRET_QUERY_FRAGMENTS = (
    "token",
    "secret",
    "password",
    "passwd",
    "credential",
    "api_key",
    "apikey",
    "signature",
    "access_key",
    "auth",
)
SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(
        r"(?i)(?:api[_-]?key|access[_-]?token|password|secret)\s*[:=]\s*\S+"
    ),
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


def _validate_evidence_ref(ref: str) -> None:
    if not ref.startswith(SAFE_EVIDENCE_PREFIXES):
        raise QualificationInputError(
            "evidence refs must be repository/Git/fixture/HTTPS references, not local paths"
        )
    if ref.startswith("https://"):
        parsed = urlsplit(ref)
        if parsed.scheme != "https" or not parsed.hostname:
            raise QualificationInputError("HTTPS evidence ref has a malformed host")
        if parsed.username is not None or parsed.password is not None:
            raise QualificationInputError("HTTPS evidence ref must not contain user information")
        if parsed.fragment:
            raise QualificationInputError("HTTPS evidence ref must not contain a fragment")
        try:
            port = parsed.port
        except ValueError as exc:
            raise QualificationInputError("HTTPS evidence ref has a malformed port") from exc
        if port is not None and not 1 <= port <= 65535:
            raise QualificationInputError("HTTPS evidence ref has a malformed port")
        for key, _value in parse_qsl(parsed.query, keep_blank_values=True):
            normalized = key.lower().replace("-", "_")
            if any(fragment in normalized for fragment in SECRET_QUERY_FRAGMENTS):
                raise QualificationInputError(
                    "HTTPS evidence ref contains a secret-like query parameter"
                )
        return

    prefix, token = ref.split(":", 1)
    if prefix not in {"git", "repo", "fixture"} or not SAFE_EVIDENCE_TOKEN.fullmatch(token):
        raise QualificationInputError(
            "non-HTTPS evidence ref must contain only normalized reference characters"
        )


def _catalog() -> dict[str, Any]:
    data = _load_json(CATALOG)
    if not isinstance(data, dict):
        raise QualificationInputError("qualification catalog must be an object")
    if data.get("schema") != CATALOG_SCHEMA:
        raise QualificationInputError("unsupported qualification catalog schema")
    if data.get("authority") != AUTHORITY:
        raise QualificationInputError("qualification catalog must remain advisory_only")

    fixtures = data.get("fixtures")
    if not isinstance(fixtures, list) or not fixtures:
        raise QualificationInputError("qualification catalog must contain fixtures")
    fixture_ids: set[str] = set()
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise QualificationInputError("qualification fixture must be an object")
        if set(fixture) != {"id", "repository", "base_commit", "catalog_path"}:
            raise QualificationInputError(
                "qualification fixture must contain id, repository, base_commit and catalog_path only"
            )
        fixture_id = fixture.get("id")
        if not isinstance(fixture_id, str) or not SAFE_IDENTIFIER.fullmatch(fixture_id):
            raise QualificationInputError("qualification fixture id must be normalized")
        if fixture_id in fixture_ids:
            raise QualificationInputError(f"duplicate qualification fixture {fixture_id}")
        fixture_ids.add(fixture_id)
        repository = fixture.get("repository")
        if not isinstance(repository, str) or not SAFE_REPOSITORY.fullmatch(repository):
            raise QualificationInputError(
                f"qualification fixture {fixture_id} has invalid repository"
            )
        base_commit = fixture.get("base_commit")
        if not isinstance(base_commit, str) or not HEX40.fullmatch(base_commit):
            raise QualificationInputError(
                f"qualification fixture {fixture_id} has invalid base_commit"
            )
        catalog_path = fixture.get("catalog_path")
        if (
            not isinstance(catalog_path, str)
            or not catalog_path
            or catalog_path.startswith("/")
            or ".." in Path(catalog_path).parts
        ):
            raise QualificationInputError(
                f"qualification fixture {fixture_id} has invalid catalog_path"
            )

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
        fixture_id = scenario.get("fixture_id")
        if fixture_id not in fixture_ids:
            raise QualificationInputError(
                f"scenario {scenario_id} references unknown fixture {fixture_id}"
            )
        required_evidence = scenario.get("required_evidence_refs")
        if not isinstance(required_evidence, list) or not required_evidence:
            raise QualificationInputError(
                f"scenario {scenario_id} must define required_evidence_refs"
            )
        if len(required_evidence) != len(set(required_evidence)):
            raise QualificationInputError(
                f"scenario {scenario_id} has duplicate required_evidence_refs"
            )
        for ref in required_evidence:
            if not isinstance(ref, str) or not ref:
                raise QualificationInputError(
                    f"scenario {scenario_id} has invalid required_evidence_refs"
                )
            _validate_evidence_ref(ref)
        expected_fixture_ref = f"fixture:{fixture_id}/{scenario_id}"
        if expected_fixture_ref not in required_evidence:
            raise QualificationInputError(
                f"scenario {scenario_id} evidence does not bind its fixture/scenario identity"
            )
        fixture = next(item for item in fixtures if item["id"] == fixture_id)
        if f"git:{fixture['base_commit']}" not in required_evidence:
            raise QualificationInputError(
                f"scenario {scenario_id} evidence does not bind fixture base commit"
            )
        if f"repo:{fixture['catalog_path']}" not in required_evidence:
            raise QualificationInputError(
                f"scenario {scenario_id} evidence does not bind fixture catalog path"
            )
        for key in ("forbidden_actions", "required_decisions"):
            values = scenario.get(key)
            if not isinstance(values, list) or not all(
                isinstance(value, str) and value for value in values
            ):
                raise QualificationInputError(
                    f"scenario {scenario_id} has invalid {key}"
                )
            if not all(SAFE_IDENTIFIER.fullmatch(value) for value in values):
                raise QualificationInputError(
                    f"scenario {scenario_id} has non-normalized {key}"
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
            "fixture_id": str(scenario.get("fixture_id") or ""),
            "sha256": scenario_sha256(scenario),
        }
        for scenario in data["scenarios"]
    ]


def _scenario_by_id(scenario_id: str) -> dict[str, Any]:
    for scenario in _catalog()["scenarios"]:
        if scenario.get("id") == scenario_id:
            return scenario
    raise QualificationInputError(f"unknown qualification scenario {scenario_id}")


def _fixture_by_id(fixture_id: str) -> dict[str, Any]:
    for fixture in _catalog()["fixtures"]:
        if fixture.get("id") == fixture_id:
            return fixture
    raise QualificationInputError(f"unknown qualification fixture {fixture_id}")


def _reject_sensitive_values(value: Any, path: str = "result") -> None:
    if isinstance(value, str):
        if any(pattern.search(value) for pattern in SENSITIVE_VALUE_PATTERNS):
            raise QualificationInputError(
                f"privacy-sensitive provenance value is forbidden: {path}"
            )
    elif isinstance(value, dict):
        for key, nested in value.items():
            _reject_sensitive_values(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_sensitive_values(nested, f"{path}[{index}]")


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


def _require_identifier(mapping: dict[str, Any], key: str, context: str) -> str:
    value = _require_string(mapping, key, context)
    if not SAFE_IDENTIFIER.fullmatch(value):
        raise QualificationInputError(
            f"{context}.{key} must be a normalized identifier"
        )
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


def _catalog_labels(
    value: Any,
    field: str,
    allowed: list[str],
) -> list[str]:
    labels = _string_list(value, field)
    allowed_set = set(allowed)
    unsupported = sorted(set(labels) - allowed_set)
    if unsupported:
        raise QualificationInputError(
            f"{field} contains labels outside the canonical scenario catalog: "
            + ",".join(unsupported)
        )
    if not all(SAFE_IDENTIFIER.fullmatch(label) for label in labels):
        raise QualificationInputError(f"{field} contains a non-normalized label")
    return labels


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
    _reject_sensitive_values(result)
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
    repository = _require_string(fixture, "repository", "result.fixture")
    if not SAFE_REPOSITORY.fullmatch(repository):
        raise QualificationInputError(
            "result.fixture.repository must be a normalized owner/repository identifier"
        )
    base_commit = _require_string(fixture, "base_commit", "result.fixture")
    if not HEX40.fullmatch(base_commit):
        raise QualificationInputError("result.fixture.base_commit must be a 40-char SHA")
    fixture_id = _require_identifier(fixture, "fixture_id", "result.fixture")
    if fixture_id != scenario.get("fixture_id"):
        raise QualificationInputError(
            "result.fixture.fixture_id does not match the canonical scenario fixture"
        )
    trusted_fixture = _fixture_by_id(fixture_id)
    expected_fixture = {
        "repository": trusted_fixture["repository"],
        "base_commit": trusted_fixture["base_commit"],
        "fixture_id": trusted_fixture["id"],
    }
    if fixture != expected_fixture:
        raise QualificationInputError(
            "result.fixture does not exactly match the canonical fixture catalog"
        )

    executor = result.get("executor")
    if not isinstance(executor, dict):
        raise QualificationInputError("result.executor must be an object")
    expected_executor_keys = {"actor", "mechanism", "model_label", "harness_version"}
    if set(executor) != expected_executor_keys:
        raise QualificationInputError(
            "result.executor must contain actor, mechanism, model_label and harness_version only"
        )
    for key in sorted(expected_executor_keys):
        _require_identifier(executor, key, "result.executor")

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

    _catalog_labels(
        result.get("actions"),
        "result.actions",
        list(scenario["forbidden_actions"]),
    )
    _catalog_labels(
        result.get("decisions"),
        "result.decisions",
        list(scenario["required_decisions"]),
    )
    evidence_refs = _string_list(
        result.get("evidence_refs"),
        "result.evidence_refs",
        nonempty=True,
    )
    for ref in evidence_refs:
        _validate_evidence_ref(ref)
    expected_evidence = list(scenario["required_evidence_refs"])
    if evidence_refs != expected_evidence:
        raise QualificationInputError(
            "result.evidence_refs do not exactly match the canonical scenario fixture contract"
        )

    usage = result.get("usage")
    if not isinstance(usage, dict):
        raise QualificationInputError("result.usage must be an object")
    if set(usage) != {"input_tokens", "output_tokens", "source", "complete"}:
        raise QualificationInputError(
            "result.usage must contain input_tokens, output_tokens, source and complete only"
        )
    _require_identifier(usage, "source", "result.usage")
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


def _secure_output_parts(output: Path) -> tuple[str, ...]:
    """Return a lexical repo-relative output path confined to OUTPUT_ROOT."""
    try:
        root_relative = OUTPUT_ROOT.relative_to(ROOT)
    except ValueError as exc:
        raise QualificationInputError(
            "qualification output root must remain inside the repository"
        ) from exc

    if output.is_absolute():
        try:
            relative = output.relative_to(ROOT)
        except ValueError as exc:
            raise QualificationInputError(
                "qualification output must remain under .onecompany-evidence/qualification"
            ) from exc
    else:
        relative = output

    parts = tuple(relative.parts)
    root_parts = tuple(root_relative.parts)
    if (
        not parts
        or any(part in {"", ".", ".."} for part in parts)
        or len(parts) <= len(root_parts)
        or parts[: len(root_parts)] != root_parts
    ):
        raise QualificationInputError(
            "qualification output must remain under .onecompany-evidence/qualification"
        )
    return parts


def _secure_directory_flags() -> int:
    """Return fail-closed flags for directory-descriptor traversal."""
    if (
        not hasattr(os, "O_DIRECTORY")
        or not hasattr(os, "O_NOFOLLOW")
        or os.open not in os.supports_dir_fd
        or os.mkdir not in os.supports_dir_fd
    ):
        raise QualificationInputError(
            "secure qualification file output is unsupported on this platform; use stdout"
        )
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


def _open_secure_output_parent(parts: tuple[str, ...]) -> tuple[int, str]:
    """Open every output ancestor by descriptor without following symlinks."""
    directory_flags = _secure_directory_flags()
    try:
        repo_anchor = ROOT.resolve(strict=True)
        current_fd = os.open(repo_anchor, directory_flags)
    except OSError as exc:
        raise QualificationInputError(
            f"cannot open repository root for secure qualification output: {exc}"
        ) from exc

    try:
        for part in parts[:-1]:
            try:
                next_fd = os.open(part, directory_flags, dir_fd=current_fd)
            except FileNotFoundError:
                try:
                    os.mkdir(part, 0o700, dir_fd=current_fd)
                    next_fd = os.open(part, directory_flags, dir_fd=current_fd)
                except OSError as exc:
                    raise QualificationInputError(
                        f"cannot create secure qualification output directory {part}: {exc}"
                    ) from exc
            except OSError as exc:
                raise QualificationInputError(
                    f"qualification output path contains an unsafe directory component {part}: {exc}"
                ) from exc
            os.close(current_fd)
            current_fd = next_fd
        return current_fd, parts[-1]
    except Exception:
        os.close(current_fd)
        raise


def _open_secure_output_file(
    parent_fd: int,
    filename: str,
    *,
    overwrite: bool,
) -> int:
    """Open the final artifact without following links or truncating before validation."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if not overwrite:
        flags |= os.O_EXCL
    try:
        fd = os.open(filename, flags, 0o600, dir_fd=parent_fd)
    except FileExistsError as exc:
        raise QualificationInputError(
            "qualification output already exists; pass --overwrite to replace it"
        ) from exc
    except OSError as exc:
        raise QualificationInputError(
            f"cannot open qualification output safely: {exc}"
        ) from exc

    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise QualificationInputError(
                "qualification output must be a regular file"
            )
        if metadata.st_nlink != 1:
            raise QualificationInputError(
                "qualification output must not have multiple hard links"
            )
        if overwrite:
            os.ftruncate(fd, 0)
        return fd
    except Exception:
        os.close(fd)
        raise


def _write_or_print(
    value: Any,
    output: Path | None,
    *,
    overwrite: bool = False,
) -> None:
    text = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if output is None:
        print(text, end="")
        return

    parts = _secure_output_parts(output)
    parent_fd, filename = _open_secure_output_parent(parts)
    try:
        fd = _open_secure_output_file(parent_fd, filename, overwrite=overwrite)
    finally:
        os.close(parent_fd)

    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    except OSError as exc:
        raise QualificationInputError(f"cannot write qualification output: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    catalog_p = sub.add_parser("catalog")
    catalog_p.add_argument("--json", action="store_true")
    evaluate_p = sub.add_parser("evaluate")
    evaluate_p.add_argument("--result", required=True, type=Path)
    evaluate_p.add_argument("--output", type=Path)
    evaluate_p.add_argument("--overwrite", action="store_true")
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
        _write_or_print(provenance, args.output, overwrite=args.overwrite)
        return exit_code
    except QualificationInputError as exc:
        print(f"QUALIFICATION INVALID: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())