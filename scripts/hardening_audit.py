#!/usr/bin/env python3
"""Audit repository-wide workflow and template supply-chain invariants."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from onecompany_lib import ROOT

SHA40 = re.compile(r"^[0-9a-fA-F]{40}$")
USES_KEY = re.compile(r"(?i)(?<![A-Za-z0-9_-])['\"]?uses['\"]?\s*:\s*([^\s,}\]]+)")
USES_EMPTY = re.compile(r"(?im)(?<![A-Za-z0-9_-])['\"]?uses['\"]?\s*:\s*(?:$|[,}\]])")
WRITE_ALL = re.compile(r"(?i)(?<![A-Za-z0-9_-])['\"]?permissions['\"]?\s*:\s*['\"]?write-all['\"]?(?![A-Za-z0-9_-])")
BLOCK_PRT = re.compile(r"(?im)^\s*['\"]?pull_request_target['\"]?\s*:")
FLOW_PRT = re.compile(
    r"(?is)(?<![A-Za-z0-9_-])['\"]?on['\"]?\s*:\s*(?:\[[^\]]*\bpull_request_target\b|\{[^}]*\bpull_request_target\b)"
)


def workflow_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".yml", ".yaml"}
    )


def _strip_yaml_comments(text: str) -> str:
    """Remove YAML comments without treating # inside quoted strings as comments."""
    output: list[str] = []
    single = False
    double = False
    escaped = False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\n":
            output.append(ch)
            escaped = False
            i += 1
            continue
        if double:
            output.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                double = False
            i += 1
            continue
        if single:
            output.append(ch)
            if ch == "'":
                if i + 1 < len(text) and text[i + 1] == "'":
                    output.append("'")
                    i += 2
                    continue
                single = False
            i += 1
            continue
        if ch == '"':
            double = True
            output.append(ch)
        elif ch == "'":
            single = True
            output.append(ch)
        elif ch == "#":
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        else:
            output.append(ch)
        i += 1
    return "".join(output)


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def audit_workflow(path: Path) -> list[str]:
    errors: list[str] = []
    text = _strip_yaml_comments(path.read_text(encoding="utf-8"))
    relative = path.relative_to(ROOT)

    # Cover both block and YAML-flow event syntax. Flow syntax is a common way
    # line-oriented audits are bypassed, so policy checks are representation-agnostic.
    if BLOCK_PRT.search(text) or FLOW_PRT.search(text):
        errors.append(f"{relative}: pull_request_target is forbidden")
    if WRITE_ALL.search(text):
        errors.append(f"{relative}: permissions: write-all is forbidden")

    if USES_EMPTY.search(text):
        errors.append(f"{relative}: uses must be an explicit scalar on the same mapping entry")

    for match in USES_KEY.finditer(text):
        raw = _unquote(match.group(1))
        if raw.startswith("./"):
            continue
        if raw.startswith("docker://"):
            image = raw[len("docker://"):]
            if not re.search(r"@sha256:[0-9a-fA-F]{64}$", image):
                errors.append(f"{relative}: docker action {raw} is not pinned to an immutable sha256 digest")
            continue
        if "@" not in raw:
            errors.append(f"{relative}: external action {raw} is missing an immutable revision")
            continue
        action, revision = raw.rsplit("@", 1)
        if not action or not SHA40.fullmatch(revision):
            errors.append(
                f"{relative}: external action {raw} is not pinned to immutable 40-hex SHA"
            )
    return sorted(set(errors))


def main() -> int:
    errors: list[str] = []
    workflows = ROOT / ".github" / "workflows"
    discovered = workflow_files(workflows)
    if not discovered:
        errors.append(".github/workflows contains no executable workflow to audit")
    for path in discovered:
        errors.extend(audit_workflow(path))

    template_dir = ROOT / ".onecompany" / "templates" / "workflows"
    if template_dir.exists():
        for path in template_dir.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".yml", ".yaml"}:
                errors.append(
                    f"{path.relative_to(ROOT)}: provider/supervisor template became executable; "
                    "keep templates disabled until project setup explicitly promotes them"
                )

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"Hardening audit FAILED ({len(errors)} error(s)).")
        return 1
    print(f"Hardening audit PASS ({len(discovered)} workflow(s) audited).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
