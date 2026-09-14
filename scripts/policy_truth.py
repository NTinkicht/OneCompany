#!/usr/bin/env python3
"""Generate and validate the mechanical truth status of machine policy keys.

A policy key is ENFORCED only when a production validator/authority module
contains a literal reference to that key (or it is structural schema metadata).
Keys without a mechanical consumer are GUIDANCE. A separate claims file may
assert important guarantees, but CI rejects any ENFORCED claim that the source
inventory cannot substantiate.

Policy-claim history is monotonic on pull requests: an existing claim from the
exact reviewed base may not disappear silently. Retirement must remain visible
as an explicit REMOVED record with rationale and provenance, and a retired key
must no longer exist in policy nor be consumed by an enforcing module.

This deliberately prefers a conservative false-negative (GUIDANCE) over
pretending a decorative value is enforced.
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from onecompany_lib import CONTROL, ROOT, load_json

POLICY_FILES = (
    "actors.json",
    "architecture.json",
    "budget.json",
    "config.json",
    "dispatch.json",
    "governance.json",
    "identity.json",
    "kernel-boundary.json",
    "ledger.json",
    "overlays.json",
    "patterns.json",
    "planning.json",
    "quality-baseline.json",
    "quality.json",
    "readiness.json",
    "required-checks.json",
    "roles.json",
    "routing.json",
    "supervision.json",
)

# Modules that only render/explain state cannot make a policy mechanically true.
NON_ENFORCING_MODULES = {
    "status.py",
    "doctor.py",
    "onboard.py",
}
STRUCTURAL_KEYS = {"$schema", "schema_version"}
CLAIMS_PATH = ".onecompany/policy-claims.json"


def _normalized_path(parts: tuple[str, ...]) -> str:
    return "/" + "/".join(parts)


def enumerate_keys(value: Any, parts: tuple[str, ...] = ()) -> list[tuple[str, str]]:
    """Return every object key, normalizing array indexes to ``*``."""
    result: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key in sorted(value):
            current = (*parts, str(key))
            result.append((_normalized_path(current), str(key)))
            result.extend(enumerate_keys(value[key], current))
    elif isinstance(value, list):
        for item in value:
            result.extend(enumerate_keys(item, (*parts, "*")))
    # Deduplicate paths produced by repeated array records.
    return sorted(set(result))


def source_key_index(scripts_dir: Path | None = None) -> dict[str, set[str]]:
    scripts = scripts_dir or (ROOT / "scripts")
    index: dict[str, set[str]] = defaultdict(set)
    for path in sorted(scripts.glob("*.py")):
        if path.name == Path(__file__).name:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                # Exact string literals are the auditable policy-access seam.
                index[node.value].add(path.name)
    return index


def classify_key(key: str, consumers: set[str]) -> str:
    if key in STRUCTURAL_KEYS:
        return "ENFORCED"
    enforcing = {name for name in consumers if name not in NON_ENFORCING_MODULES}
    return "ENFORCED" if enforcing else "GUIDANCE"


def generate_inventory(
    control: Path | None = None,
    *,
    source_index: dict[str, set[str]] | None = None,
) -> list[dict[str, Any]]:
    root = control or CONTROL
    index = source_index if source_index is not None else source_key_index()
    inventory: list[dict[str, Any]] = []
    for name in POLICY_FILES:
        path = root / name
        if not path.exists():
            continue
        try:
            document = load_json(path)
        except Exception as exc:
            inventory.append(
                {
                    "file": name,
                    "path": "/",
                    "key": "<invalid-json>",
                    "classification": "REMOVED",
                    "owner": "schema_validate.py",
                    "evidence": [f"invalid JSON: {exc}"],
                }
            )
            continue
        for pointer, key in enumerate_keys(document):
            consumers = set(index.get(key, set()))
            classification = classify_key(key, consumers)
            if key in STRUCTURAL_KEYS:
                owner = "schema_validate.py"
                evidence = ["schema_validate.py"]
            elif classification == "ENFORCED":
                enforcing = sorted(name for name in consumers if name not in NON_ENFORCING_MODULES)
                owner = enforcing[0]
                evidence = enforcing
            else:
                owner = "guidance-only"
                evidence = sorted(consumers)
            inventory.append(
                {
                    "file": name,
                    "path": pointer,
                    "key": key,
                    "classification": classification,
                    "owner": owner,
                    "evidence": evidence,
                }
            )
    return inventory


def _claim_matches(entry: dict[str, Any], claim: dict[str, Any]) -> bool:
    return (
        fnmatch.fnmatch(entry["file"], str(claim.get("file") or ""))
        and fnmatch.fnmatch(entry["path"], str(claim.get("path") or ""))
    )


def _claim_identity(claim: dict[str, Any]) -> tuple[str, str]:
    return (str(claim.get("file") or ""), str(claim.get("path") or ""))


def _claim_key(claim: dict[str, Any]) -> str | None:
    """Return an exact terminal key for source-consumer checks when possible."""
    path = str(claim.get("path") or "")
    if not path.startswith("/") or any(token in path for token in ("*", "?", "[")):
        return None
    terminal = path.rsplit("/", 1)[-1]
    if not terminal:
        return None
    return terminal.replace("~1", "/").replace("~0", "~")


def validate_claims(
    inventory: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    *,
    root: Path | None = None,
    source_index: dict[str, set[str]] | None = None,
) -> list[str]:
    repo = root or ROOT
    index = source_index if source_index is not None else source_key_index(repo / "scripts")
    errors: list[str] = []
    valid_classes = {"ENFORCED", "GUIDANCE", "REMOVED"}
    seen: set[tuple[str, str]] = set()

    for position, claim in enumerate(claims):
        identity = _claim_identity(claim)
        if identity in seen:
            errors.append(
                f"claim[{position}] duplicates policy-claim identity {identity[0]}:{identity[1]}"
            )
        seen.add(identity)

        declared = claim.get("classification")
        if declared not in valid_classes:
            errors.append(f"claim[{position}] has invalid classification {declared!r}")
            continue
        matches = [entry for entry in inventory if _claim_matches(entry, claim)]
        if declared == "REMOVED":
            rationale = claim.get("removal_rationale")
            provenance = claim.get("removal_provenance")
            if not isinstance(rationale, str) or not rationale.strip():
                errors.append(f"claim[{position}] REMOVED requires removal_rationale")
            if not isinstance(provenance, str) or not provenance.strip():
                errors.append(f"claim[{position}] REMOVED requires removal_provenance")
            if matches:
                errors.append(
                    f"claim[{position}] declares REMOVED but still matches "
                    f"{matches[0]['file']}:{matches[0]['path']}"
                )
            key = _claim_key(claim)
            if key is not None:
                enforcing = sorted(
                    name for name in index.get(key, set()) if name not in NON_ENFORCING_MODULES
                )
                if enforcing:
                    errors.append(
                        f"claim[{position}] declares REMOVED but policy key {key!r} is still "
                        f"consumed by enforcing module(s): {', '.join(enforcing)}"
                    )
            continue
        if not matches:
            errors.append(
                f"claim[{position}] matches no current policy key: "
                f"{claim.get('file')}:{claim.get('path')}"
            )
            continue
        if declared == "ENFORCED":
            unsupported = [entry for entry in matches if entry["classification"] != "ENFORCED"]
            if unsupported:
                sample = unsupported[0]
                errors.append(
                    "unsupported ENFORCED claim for "
                    f"{sample['file']}:{sample['path']}; no mechanical consumer"
                )
            tests = claim.get("tests") or []
            if not isinstance(tests, list) or not tests:
                errors.append(f"claim[{position}] ENFORCED requires at least one executable test evidence path")
            for test in tests:
                test_path = repo / str(test)
                if not test_path.is_file():
                    errors.append(f"claim[{position}] test evidence does not exist: {test}")
        elif declared == "GUIDANCE":
            enforced = [entry for entry in matches if entry["classification"] == "ENFORCED"]
            if enforced:
                sample = enforced[0]
                errors.append(
                    "GUIDANCE claim is consumed by an enforcing module and must not be presented as guidance: "
                    f"{sample['file']}:{sample['path']} owner={sample['owner']}"
                )
    return errors


def validate_claim_history(
    base_claims: list[dict[str, Any]],
    claims: list[dict[str, Any]],
) -> list[str]:
    """Reject silent claim deletion and resurrection relative to the exact base."""
    errors: list[str] = []
    current = {_claim_identity(claim): claim for claim in claims}
    for position, base_claim in enumerate(base_claims):
        identity = _claim_identity(base_claim)
        candidate = current.get(identity)
        if candidate is None:
            errors.append(
                "candidate silently removes existing policy claim "
                f"{identity[0]}:{identity[1]}; retain it as REMOVED with rationale and provenance"
            )
            continue
        if (
            base_claim.get("classification") == "REMOVED"
            and candidate.get("classification") != "REMOVED"
        ):
            errors.append(
                "candidate resurrects previously REMOVED policy claim "
                f"{identity[0]}:{identity[1]}; claim retirement is monotonic"
            )
    return errors


def load_claims(control: Path | None = None) -> list[dict[str, Any]]:
    root = control or CONTROL
    path = root / "policy-claims.json"
    if not path.exists():
        return []
    document = load_json(path)
    claims = document.get("claims", [])
    if not isinstance(claims, list):
        raise RuntimeError("policy-claims.json claims must be an array")
    return claims


def pull_request_base_sha() -> str | None:
    """Return the exact GitHub PR base SHA when running in pull_request CI."""
    if os.environ.get("GITHUB_EVENT_NAME") != "pull_request":
        return None
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path:
        raise RuntimeError("pull_request CI is missing GITHUB_EVENT_PATH")
    try:
        payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
        base_sha = payload["pull_request"]["base"]["sha"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot determine exact pull-request base SHA: {exc}") from exc
    if not isinstance(base_sha, str) or len(base_sha) != 40:
        raise RuntimeError(f"invalid pull-request base SHA: {base_sha!r}")
    return base_sha


def load_claims_at_revision(revision: str, *, root: Path | None = None) -> list[dict[str, Any]]:
    repo = root or ROOT
    completed = subprocess.run(
        ["git", "show", f"{revision}:{CLAIMS_PATH}"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "git show failed"
        raise RuntimeError(
            f"exact base {revision} is missing or cannot read {CLAIMS_PATH}: {detail}"
        )
    try:
        document = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"exact-base policy claims are invalid JSON: {exc}") from exc
    claims = document.get("claims", [])
    if not isinstance(claims, list):
        raise RuntimeError("exact-base policy-claims.json claims must be an array")
    return claims


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="print generated key-level inventory")
    args = parser.parse_args()

    index = source_key_index()
    inventory = generate_inventory(source_index=index)
    claims = load_claims()
    errors = validate_claims(inventory, claims, source_index=index)

    try:
        base_sha = pull_request_base_sha()
        if base_sha is not None:
            errors.extend(validate_claim_history(load_claims_at_revision(base_sha), claims))
    except RuntimeError as exc:
        errors.append(str(exc))

    classes = {"ENFORCED": 0, "GUIDANCE": 0, "REMOVED": 0}
    for entry in inventory:
        classes[entry["classification"]] = classes.get(entry["classification"], 0) + 1

    if args.json:
        print(json.dumps({"inventory": inventory, "counts": classes, "errors": errors}, indent=2))
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"Policy truthfulness FAILED ({len(errors)} error(s)).")
        return 1
    print(
        "Policy truthfulness PASS "
        f"({len(inventory)} keys; enforced={classes['ENFORCED']}; "
        f"guidance={classes['GUIDANCE']}; removed={classes['REMOVED']})."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
