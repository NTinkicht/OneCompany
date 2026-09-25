#!/usr/bin/env python3
"""Fail-closed, bounded Mistral advisory review *data* parser.

The trusted GitHub Actions parent validates model output before publication.
It never treats model-supplied instructions or approval assertions as authority.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

SHA = re.compile(r"[a-f0-9]{40}\Z")
FILE = re.compile(r"(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\Z")
SEVERITIES = frozenset({"INFO", "LOW", "MEDIUM", "MAJOR", "HIGH", "CRITICAL"})
VERDICTS = frozenset({"NO_BLOCKING_FINDINGS", "CHANGES_REQUIRED", "INSUFFICIENT_EVIDENCE"})
MAX_BYTES = 15000


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("MISTRAL_DUPLICATE_KEY")
        result[key] = value
    return result


def _plain(value: object, maximum: int) -> bool:
    return (type(value) is str and 1 <= len(value) <= maximum
            and value.strip() == value
            and not any(ord(char) < 32 or ord(char) == 127 for char in value))


def _inert(value: str) -> str:
    """Render model-controlled prose as inert GitHub text without active markup/mentions."""
    # quote=False: output is Markdown text, never an HTML attribute, and the
    # apostrophe entity (&#x27;) would have its "#" re-encoded below.
    escaped = html.escape(value, quote=False)
    # Encode Markdown metacharacters as entities: GitHub parses entities as
    # literal characters after inline Markdown delimiter recognition.
    return re.sub(r"[@*_`\[\]()!#>~\\|]", lambda match: f"&#{ord(match.group())};", escaped)


def parse_result(raw: bytes, *, pr: int, head: str, base: str) -> dict:
    if (type(raw) is not bytes or not 1 <= len(raw) <= MAX_BYTES
            or type(pr) is not int or not 1 <= pr <= 999999
            or type(head) is not str or not SHA.fullmatch(head)
            or type(base) is not str or not SHA.fullmatch(base)
            or head == base):
        raise ValueError("MISTRAL_RESULT_BOUND_OR_TARGET_INVALID")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(
                               ValueError("MISTRAL_NONFINITE")))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError("MISTRAL_RESULT_JSON_INVALID") from exc
    if type(value) is not dict or set(value) != {
        "version", "repo", "pr", "head_sha", "base_sha", "verdict",
        "summary", "findings",
    }:
        raise ValueError("MISTRAL_RESULT_FIELDS_INVALID")
    if (type(value["version"]) is not int or value["version"] != 1
            or value["repo"] != "NTinkicht/OneCompany"
            or type(value["pr"]) is not int or value["pr"] != pr
            or value["head_sha"] != head or value["base_sha"] != base
            or type(value["verdict"]) is not str
            or value["verdict"] not in VERDICTS
            or not _plain(value["summary"], 1800)
            or type(value["findings"]) is not list
            or len(value["findings"]) > 12):
        raise ValueError("MISTRAL_RESULT_CONTENT_INVALID")
    for finding in value["findings"]:
        if type(finding) is not dict or set(finding) != {
            "severity", "path", "line", "description",
        }:
            raise ValueError("MISTRAL_FINDING_FIELDS_INVALID")
        path = finding["path"]
        if (type(finding["severity"]) is not str
                or finding["severity"] not in SEVERITIES
                or not _plain(path, 240)
                or not FILE.fullmatch(path)
                or any(part in {".", "..", ".git", ".vibe"}
                       for part in Path(path).parts)
                or type(finding["line"]) is not int
                or not 1 <= finding["line"] <= 1_000_000
                or not _plain(finding["description"], 1200)):
            raise ValueError("MISTRAL_FINDING_INVALID")
    if value["verdict"] == "CHANGES_REQUIRED" and not value["findings"]:
        raise ValueError("MISTRAL_CHANGE_REQUEST_WITHOUT_FINDINGS")
    if value["verdict"] == "INSUFFICIENT_EVIDENCE":
        raise ValueError("MISTRAL_INSUFFICIENT_EVIDENCE")
    if value["verdict"] == "NO_BLOCKING_FINDINGS" and any(
        f["severity"] in {"MEDIUM", "MAJOR", "HIGH", "CRITICAL"}
        for f in value["findings"]
    ):
        raise ValueError("MISTRAL_VERDICT_INCONSISTENT")
    return value


def format_comment(value: dict, *, run_url: str) -> str:
    # Returned data is an ADVISORY COMMENT, never GitHub APPROVE or a merge gate.
    lines = [
        "**Mistral Vibe exact-head advisory code review (NON-GATING)**",
        "GitHub publisher: github-actions[bot]; model: mistral-vibe.",
        f"PR #{value['pr']}; head `{value['head_sha']}`; base `{value['base_sha']}`.",
        f"Trusted run: {run_url}",
        f"Verdict: {value['verdict']}.",
        "",
        _inert(value["summary"]),
        "",
    ]
    for item in value["findings"]:
        lines.append(
            f"- [{item['severity']}] `{item['path']}:{item['line']}` - {_inert(item['description'])}"
        )
    lines.extend(["", "No approval, binding reviewer gate, code write or merge authority."])
    return "\n".join(lines) + "\n"


BINDING_MARKER = "ONECOMPANY_MISTRAL_BINDING_REVIEW_V1"


def format_binding_review(value: dict, *, run_url: str,
                          run_id: int, run_sha: str) -> tuple[str, str]:
    """The trusted parent chooses the GitHub review event, never model prose.

    A successful one-shot model review is eligible only as an independent
    technical reviewer of code the model did NOT materially author. The trusted
    publisher and OneCompany binding gate must verify this review's origin and
    exact base/head independently.
    """
    if (type(run_id) is not int or run_id < 1
            or type(run_sha) is not str or not SHA.fullmatch(run_sha)
            or type(run_url) is not str or not run_url.endswith(
                f"/NTinkicht/OneCompany/actions/runs/{run_id}"
            )):
        raise ValueError("MISTRAL_BINDING_RUN_INVALID")
    if value.get("verdict") == "NO_BLOCKING_FINDINGS":
        event, outcome = "APPROVE", "PASS"
    elif value.get("verdict") == "CHANGES_REQUIRED":
        event, outcome = "REQUEST_CHANGES", "FAIL"
    else:
        raise ValueError("MISTRAL_BINDING_VERDICT_INVALID")
    marker = (
        f"<!-- {BINDING_MARKER} pr={value['pr']} "
        f"head={value['head_sha']} base={value['base_sha']} "
        f"run={run_id} run_sha={run_sha} verdict={outcome} -->"
    )
    lines = [
        "**Mistral Vibe independent exact-head technical review**",
        f"Result: {outcome} (model: {value['verdict']}).",
        f"PR #{value['pr']}; head `{value['head_sha']}`; "
        f"base `{value['base_sha']}`.",
        f"Trusted run: {run_url}",
        "Publisher: github-actions[bot]; material reviewer: mistral-vibe.",
        "Passing technical review never overrides deterministic CI, "
        "exact-base/head, non-self authorship, scope, assurance or merge rules.",
        "",
        _inert(value["summary"]),
        "",
    ]
    for item in value["findings"]:
        lines.append(
            f"- [{item['severity']}] `{item['path']}:{item['line']}` - "
            f"{_inert(item['description'])}"
        )
    lines.extend(["", marker])
    return event, "\n".join(lines) + "\n"


def main() -> int:
    """Validate untrusted Vibe output with only bounded, trusted CLI inputs."""
    import sys
    if len(sys.argv) != 5:
        return 72
    try:
        pr = int(sys.argv[1])
        raw_path = Path(sys.argv[4])
        if raw_path.is_symlink() or not raw_path.is_file():
            return 72
        # Hard bound before reading model-authored data.
        if not 1 <= raw_path.stat().st_size <= MAX_BYTES:
            return 72
        parse_result(
            raw_path.read_bytes(), pr=pr,
            head=sys.argv[2], base=sys.argv[3],
        )
    except (ValueError, OSError, OverflowError):
        if "MISTRAL_INSUFFICIENT_EVIDENCE" in str(sys.exc_info()[1]):
            return 71
        return 72
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
