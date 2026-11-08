#!/usr/bin/env python3
"""Deterministic, read-only agent-communication check (OC-P1-06 slice 1, #461).

Input: ``{"revision": 40-hex, "trusted_actors": [name], "max_attempts": int>=1, "messages": [...]}``
with messages in delivery order, each ``{"id", "actor", "seq": int>=0, "idempotency_key",
"payload_digest": 64-hex, "kind": handoff|approval|status, "authority": ledger|message,
"claims_approval": bool, "signature": valid|invalid|missing, "attempt": int>=1,
"effect": applied|ignored|rejected}``. Only ``applied`` messages are checked: they must come from a
trusted actor with a valid signature, apply each idempotency key once with one payload, keep
``seq`` strictly increasing per actor, stay within ``max_attempts``, never let a non-approval
message claim approval, and only apply an approval whose authority is the ledger. No network,
no writes, no clock.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HEX40 = re.compile(r"[0-9a-fA-F]{40}")
HEX64 = re.compile(r"[0-9a-fA-F]{64}")
KINDS = {"handoff", "approval", "status"}
AUTHORITY = {"ledger", "message"}
SIGNATURE = {"valid", "invalid", "missing"}
EFFECT = {"applied", "ignored", "rejected"}


def _name(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _int(value: object, minimum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


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
    trusted = data.get("trusted_actors")
    if not isinstance(trusted, list) or not trusted or not all(_name(a) for a in trusted):
        raise ValueError("report needs a non-empty trusted_actors list of names")
    if not _int(data.get("max_attempts"), 1):
        raise ValueError("max_attempts must be an integer >= 1")
    messages = data.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("report has no non-empty messages list")
    seen: set[str] = set()
    for m in messages:
        if not isinstance(m, dict):
            raise ValueError("message is not an object")
        mid = m.get("id")
        if not _name(mid):
            raise ValueError("message needs a non-empty string id")
        if mid in seen:
            raise ValueError(f"duplicate message id: {mid}")
        seen.add(mid)
        if not _name(m.get("actor")) or not _name(m.get("idempotency_key")):
            raise ValueError(f"{mid} needs actor and idempotency_key")
        if not _int(m.get("seq"), 0) or not _int(m.get("attempt"), 1):
            raise ValueError(f"{mid} needs integer seq >= 0 and attempt >= 1")
        if not isinstance(m.get("payload_digest"), str) or not HEX64.fullmatch(m["payload_digest"]):
            raise ValueError(f"{mid} payload_digest must be a 64-hex digest")
        if not isinstance(m.get("claims_approval"), bool):
            raise ValueError(f"{mid} claims_approval must be a boolean")
        for field, allowed in (("kind", KINDS), ("authority", AUTHORITY),
                               ("signature", SIGNATURE), ("effect", EFFECT)):
            if not isinstance(m.get(field), str) or m[field] not in allowed:
                raise ValueError(f"{mid} has unknown {field}")
    return data


def evaluate(report: dict) -> dict:
    trusted = set(report["trusted_actors"])
    problems: list[str] = []
    applied_keys: dict[str, dict] = {}
    last_seq: dict[str, int] = {}
    applied = 0
    for m in report["messages"]:
        if m["effect"] != "applied":
            continue
        applied += 1
        mid, actor, key = m["id"], m["actor"], m["idempotency_key"]
        if actor not in trusted or m["signature"] != "valid":
            problems.append(f"SPOOFED_ACTOR {mid} {actor} signature={m['signature']}")
        if key in applied_keys:
            if applied_keys[key]["payload_digest"].lower() != m["payload_digest"].lower():
                problems.append(f"KEY_REUSE_CONFLICT {mid} key {key} reused with a different payload")
            else:
                problems.append(f"DUPLICATE_APPLIED {mid} key {key} already applied by {applied_keys[key]['id']}")
        else:
            applied_keys[key] = m
        if actor in last_seq and m["seq"] <= last_seq[actor]:
            problems.append(f"ORDER_VIOLATION {mid} {actor} seq {m['seq']} after {last_seq[actor]}")
        last_seq[actor] = max(m["seq"], last_seq.get(actor, m["seq"]))
        if m["attempt"] > report["max_attempts"]:
            problems.append(f"RETRY_UNBOUNDED {mid} attempt {m['attempt']} > {report['max_attempts']}")
        if m["kind"] != "approval" and m["claims_approval"]:
            problems.append(f"HANDOFF_AS_APPROVAL {mid} {m['kind']} message claims approval")
        if m["kind"] == "approval" and m["authority"] != "ledger":
            problems.append(f"UNTRUSTED_APPROVAL {mid} approval authority is {m['authority']}")
    return {"messages": len(report["messages"]), "applied": applied, "problems": problems}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only agent communication check.")
    parser.add_argument("report", help="communication report JSON file")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args(argv)
    try:
        result = evaluate(load_report(Path(args.report)))
    except ValueError as exc:
        print(f"comms-check: UNABLE TO VERIFY ({exc})", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"comms-check: {result['applied']}/{result['messages']} applied, {len(result['problems'])} problems")
        for item in result["problems"]:
            print(f"  {item}")
    return 1 if result["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
