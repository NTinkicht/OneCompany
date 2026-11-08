#!/usr/bin/env python3
"""Deterministic, read-only dependency-update / staged-release check (OC-P1-09 slice 1, #463).

Input: ``{"revision": 40-hex, "stop_active": bool, "manifests": [{"id", "manifest_digest": 64-hex,
"lockfile_digest": 64-hex|null, "lock_for_manifest_digest": 64-hex|null}], "updates": [{"id",
"manifest": <manifest id>, "source_digest_expected": 64-hex, "source_digest_actual": 64-hex,
"stage": staging|production, "canary": pass|fail|not_run, "promoted": bool, "rolled_back": bool,
"rollback_proof": verified|missing, "authorized": bool, "started_after_stop": bool}]}``.
Every lockfile must exist and have been generated from the current manifest digest; every update
must keep its source digest, may only be promoted after a passing canary with verified rollback
proof, must be rolled back or unpromoted after a failed canary, may reach production only with
separate human authorization, and must not start while the emergency stop is active.
No network, no writes, no clock.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HEX40 = re.compile(r"[0-9a-fA-F]{40}")
HEX64 = re.compile(r"[0-9a-fA-F]{64}")
STAGES = {"staging", "production"}
CANARY = {"pass", "fail", "not_run"}
ROLLBACK = {"verified", "missing"}


def _name(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _hex64(value: object) -> bool:
    return isinstance(value, str) and bool(HEX64.fullmatch(value))


def _opt_hex64(value: object) -> bool:
    return value is None or _hex64(value)


def load_report(path: Path) -> dict:
    """Return the validated report; raise ValueError on anything malformed."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"report unreadable: {path.name} ({exc.__class__.__name__})") from exc
    if not isinstance(data, dict):
        raise ValueError("report is not an object")
    if not isinstance(data.get("revision"), str) or not HEX40.fullmatch(data["revision"]):
        raise ValueError("report needs a 40-hex revision")
    if not isinstance(data.get("stop_active"), bool):
        raise ValueError("stop_active must be a boolean")
    manifests, updates = data.get("manifests"), data.get("updates")
    if not isinstance(manifests, list) or not manifests:
        raise ValueError("report has no non-empty manifests list")
    if not isinstance(updates, list):
        raise ValueError("updates must be a list")
    ids: set[str] = set()
    for m in manifests:
        if not isinstance(m, dict) or not _name(m.get("id")):
            raise ValueError("manifest needs a non-empty string id")
        if m["id"] in ids:
            raise ValueError(f"duplicate manifest id: {m['id']}")
        ids.add(m["id"])
        if not _hex64(m.get("manifest_digest")):
            raise ValueError(f"{m['id']} manifest_digest must be a 64-hex digest")
        if not _opt_hex64(m.get("lockfile_digest")) or not _opt_hex64(m.get("lock_for_manifest_digest")):
            raise ValueError(f"{m['id']} lock digests must be 64-hex or null")
    seen: set[str] = set()
    for u in updates:
        if not isinstance(u, dict) or not _name(u.get("id")):
            raise ValueError("update needs a non-empty string id")
        uid = u["id"]
        if uid in seen:
            raise ValueError(f"duplicate update id: {uid}")
        seen.add(uid)
        if u.get("manifest") not in ids:
            raise ValueError(f"{uid} references an unknown manifest")
        if not _hex64(u.get("source_digest_expected")) or not _hex64(u.get("source_digest_actual")):
            raise ValueError(f"{uid} source digests must be 64-hex")
        for field in ("promoted", "rolled_back", "authorized", "started_after_stop"):
            if not isinstance(u.get(field), bool):
                raise ValueError(f"{uid} {field} must be a boolean")
        for field, allowed in (("stage", STAGES), ("canary", CANARY), ("rollback_proof", ROLLBACK)):
            if not isinstance(u.get(field), str) or u[field] not in allowed:
                raise ValueError(f"{uid} has unknown {field}")
    return data


def evaluate(report: dict) -> dict:
    problems: list[str] = []
    for m in report["manifests"]:
        mid = m["id"]
        if m["lockfile_digest"] is None:
            problems.append(f"LOCKFILE_MISSING {mid}")
        elif m["lock_for_manifest_digest"] is None or m["lock_for_manifest_digest"].lower() != m["manifest_digest"].lower():
            problems.append(f"LOCKFILE_STALE {mid} lockfile not generated from the current manifest")
    for u in report["updates"]:
        uid = u["id"]
        if u["source_digest_expected"].lower() != u["source_digest_actual"].lower():
            problems.append(f"SOURCE_TAMPER {uid} source digest differs from the expected digest")
        if report["stop_active"] and u["started_after_stop"]:
            problems.append(f"STOP_IGNORED {uid} started while the emergency stop is active")
        if u["promoted"] and u["canary"] != "pass":
            problems.append(f"UNPROVEN_PROMOTION {uid} promoted with canary {u['canary']}")
        if u["promoted"] and u["rollback_proof"] != "verified":
            problems.append(f"NO_ROLLBACK_PROOF {uid} promoted without verified rollback proof")
        if u["canary"] == "fail" and not u["promoted"] and not u["rolled_back"]:
            problems.append(f"UNRECOVERED_FAILURE {uid} failed canary was neither rolled back nor contained")
        if u["stage"] == "production" and u["promoted"] and not u["authorized"]:
            problems.append(f"PRODUCTION_UNAUTHORIZED {uid} reached production without separate human authorization")
    return {"manifests": len(report["manifests"]), "updates": len(report["updates"]), "problems": problems}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only dependency update / staged release check.")
    parser.add_argument("report", help="dependency update report JSON file")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args(argv)
    try:
        result = evaluate(load_report(Path(args.report)))
    except ValueError as exc:
        print(f"deps-check: UNABLE TO VERIFY ({exc})", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"deps-check: {result['manifests']} manifests, {result['updates']} updates, {len(result['problems'])} problems")
        for item in result["problems"]:
            print(f"  {item}")
    return 1 if result["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
