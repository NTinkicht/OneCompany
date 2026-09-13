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
# CompanyOS deliberately rejects encoded YAML semantics in executable workflows.
# This is a fail-closed canonical-subset rule: semantically significant strings
# must be visible to a deterministic text audit rather than hidden behind YAML
# escape decoding, anchors or aliases.
ENCODED_SCALAR = re.compile(r"\\(?:x[0-9A-Fa-f]{2}|u[0-9A-Fa-f]{4}|U[0-9A-Fa-f]{8})")
YAML_ANCHOR_OR_ALIAS = re.compile(r"(?m)(?:^|[\s\[{,])(?:&|\*)[A-Za-z_][A-Za-z0-9_-]*")
# Detect action-like owner/repository references anywhere after comment stripping,
# not only behind a literal `uses` token. This prevents aliases/encoded keys from
# hiding mutable external action revisions.
ACTION_REFERENCE = re.compile(
    r"(?<![A-Za-z0-9_.-])([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)@([^\s,}\]\"']+)"
)
DOCKER_REFERENCE = re.compile(r"docker://([^\s,}\]\"']+)")


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


def _audit_action_reference(relative: Path, raw: str) -> list[str]:
    errors: list[str] = []
    if raw.startswith("./"):
        return errors
    if raw.startswith("docker://"):
        image = raw[len("docker://"):]
        if not re.search(r"@sha256:[0-9a-fA-F]{64}$", image):
            errors.append(f"{relative}: docker action {raw} is not pinned to an immutable sha256 digest")
        return errors
    if "@" not in raw:
        errors.append(f"{relative}: external action {raw} is missing an immutable revision")
        return errors
    action, revision = raw.rsplit("@", 1)
    if not action or not SHA40.fullmatch(revision):
        errors.append(f"{relative}: external action {raw} is not pinned to immutable 40-hex SHA")
    return errors


def audit_workflow(path: Path) -> list[str]:
    errors: list[str] = []
    text = _strip_yaml_comments(path.read_text(encoding="utf-8"))
    relative = path.relative_to(ROOT)

    if ENCODED_SCALAR.search(text):
        errors.append(
            f"{relative}: YAML hex/unicode escapes are forbidden in executable workflows; use canonical visible scalars"
        )
    if YAML_ANCHOR_OR_ALIAS.search(text):
        errors.append(
            f"{relative}: YAML anchors/aliases are forbidden in executable workflows; keep security-relevant structure explicit"
        )

    if BLOCK_PRT.search(text) or FLOW_PRT.search(text) or "pull_request_target" in text:
        errors.append(f"{relative}: pull_request_target is forbidden")
    if WRITE_ALL.search(text):
        errors.append(f"{relative}: permissions: write-all is forbidden")

    if USES_EMPTY.search(text):
        errors.append(f"{relative}: uses must be an explicit scalar on the same mapping entry")

    # Audit literal uses mappings.
    seen: set[str] = set()
    for match in USES_KEY.finditer(text):
        raw = _unquote(match.group(1))
        seen.add(raw)
        errors.extend(_audit_action_reference(relative, raw))

    # Also audit every owner/repository@revision token globally. This catches
    # equivalent YAML representations whose key spelling is not a literal `uses`.
    for match in ACTION_REFERENCE.finditer(text):
        raw = f"{match.group(1)}@{match.group(2)}"
        if raw in seen:
            continue
        errors.extend(_audit_action_reference(relative, raw))

    for match in DOCKER_REFERENCE.finditer(text):
        raw = "docker://" + match.group(1)
        if raw in seen:
            continue
        errors.extend(_audit_action_reference(relative, raw))

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
