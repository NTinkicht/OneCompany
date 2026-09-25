#!/usr/bin/env python3
"""Zero-additional-spend Gemma hosted-inference qualification: synthetic code only.

This is a bounded canary, NOT an agent, provider credential manager, approved
independent review or model-authored PR publisher. It never executes model code.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

API = "https://openrouter.ai/api/v1/chat/completions"
FREE_MODEL = "google/gemma-4-26b-a4b-it:free"
ROOT = Path(__file__).resolve().parents[1]
MAX_RESPONSE = 64_000
TASK = (
    "On a synthetic example only, return one JSON object with exactly two string "
    "keys, code and tests. code: Python function clamp(value, low, high) that "
    "returns low for values below low, high for values above high, and value "
    "otherwise; raise ValueError if low > high. tests: deterministic unittest "
    "tests covering boundaries and invalid bounds. Do not use markdown or "
    "access files, secrets, APIs or third-party packages."
)


def check_budget(path: Path) -> None:
    """Fail before network if the trusted source policy permits any paid spend."""
    budget = json.loads(path.read_text(encoding="utf-8"))
    ai = budget["ai"]
    if (
        ai.get("additional_monthly_spend_cap") != 0
        or any(ai.get(key) is not False for key in (
            "allow_paid_fallback", "allow_overage",
            "allow_auto_topup", "allow_new_paid_vendor",
        ))
        or ai.get("unknown_cost_behavior") != "forbid"
        or budget.get("ci", {}).get("runner_cost_policy") != "included_or_free_only"
    ):
        raise ValueError("ZERO_ADDITIONAL_SPEND_POLICY_BLOCKED")


def check_model(model: str) -> None:
    """An explicit exact allowlist prohibits paid variants and router aliases."""
    if model != FREE_MODEL:
        raise ValueError("PAID_OR_UNVERIFIED_MODEL_BLOCKED")


def unique_keys(pairs: list[tuple[str, object]]) -> dict:
    """Refuse ambiguous model output rather than accepting last-key-wins JSON."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_MODEL_OUTPUT_KEY")
        result[key] = value
    return result


def parse_code_tests(content: str) -> dict:
    """Check bounded, syntactically valid proposals without running model code."""
    if not isinstance(content, str) or len(content.encode("utf-8")) > 32_000:
        raise ValueError("MODEL_OUTPUT_OVERSIZED")
    result = json.loads(content, object_pairs_hook=unique_keys)
    if not isinstance(result, dict) or set(result) != {"code", "tests"}:
        raise ValueError("MODEL_OUTPUT_FIELDS_INVALID")
    for key in ("code", "tests"):
        source = result[key]
        if not isinstance(source, str) or not source.strip():
            raise ValueError("MODEL_SOURCE_INVALID")
        if len(source.encode("utf-8")) > 12_000:
            raise ValueError("MODEL_SOURCE_OVERSIZED")
        ast.parse(source, filename=f"synthetic_{key}.py")
    return result


def probe(key: str, *, model: str = FREE_MODEL, opener=None,
          budget_path: Path = ROOT / ".onecompany/budget.json") -> dict:
    """Submit one synthetic task only when free model and budget are verified."""
    check_budget(budget_path)
    check_model(model)
    if not key or not key.strip():
        raise ValueError("OPENROUTER_API_KEY_MISSING")
    if opener is None:
        opener = urllib.request.urlopen
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "Output one JSON object only; no markdown."},
            {"role": "user", "content": TASK},
        ],
        "max_tokens": 750,
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "stream": False,
    }).encode("utf-8")
    request = urllib.request.Request(
        API, data=payload,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/NTinkicht/OneCompany",
            "X-Title": "OneCompany zero-spend Gemma synthetic canary",
        },
        method="POST",
    )
    try:
        with opener(request, timeout=30) as response:
            body = response.read(MAX_RESPONSE + 1)
    except urllib.error.HTTPError as exc:
        # Do not surface provider response bodies: they may echo request data.
        raise ValueError(f"OPENROUTER_HTTP_{exc.code}") from None
    except urllib.error.URLError:
        raise ValueError("OPENROUTER_UNAVAILABLE") from None
    if len(body) > MAX_RESPONSE:
        raise ValueError("OPENROUTER_RESPONSE_OVERSIZED")
    data = json.loads(body, object_pairs_hook=unique_keys)
    if not isinstance(data, dict):
        raise ValueError("OPENROUTER_RESPONSE_INVALID")
    usage = data.get("usage") or {}
    if not isinstance(usage, dict):
        raise ValueError("OPENROUTER_USAGE_INVALID")
    if "cost" not in usage:
        raise ValueError("NONZERO_OR_UNKNOWN_INFERENCE_COST")
    cost = usage["cost"]
    if type(cost) not in (int, float) or cost != 0:
        raise ValueError("NONZERO_OR_UNKNOWN_INFERENCE_COST")
    choices = data.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise ValueError("OPENROUTER_CHOICES_INVALID")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    proposal = parse_code_tests(content)
    return {
        "status": "SYNTHETIC_PROPOSAL_RECEIVED",
        "model_requested": model,
        "code_sha256": hashlib.sha256(proposal["code"].encode()).hexdigest(),
        "tests_sha256": hashlib.sha256(proposal["tests"].encode()).hexdigest(),
        "code_bytes": len(proposal["code"].encode()),
        "test_bytes": len(proposal["tests"].encode()),
        "model_code_executed": False,
        "repo_code_transmitted": False,
        "model_authored_repo_commit": False,
        "independent_review_qualified": False,
    }


def main() -> int:
    """CLI supports no-key offline preflight and explicit key-gated live canary."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=Path, default=ROOT / ".onecompany/budget.json")
    parser.add_argument("--model", default=FREE_MODEL)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    try:
        check_budget(args.budget)
        check_model(args.model)
        if args.live:
            result = probe(os.environ.get("OPENROUTER_API_KEY", ""), model=args.model)
        else:
            result = {
                "status": "PREFLIGHT_OK_NO_NETWORK",
                "model_requested": args.model,
                "model_code_executed": False,
                "repo_code_transmitted": False,
                "model_authored_repo_commit": False,
                "independent_review_qualified": False,
            }
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError, SyntaxError) as exc:
        # Never print model data, request bodies, key values or stack traces.
        status = str(exc) if isinstance(exc, ValueError) else "GEMMA_PROBE_INVALID"
        if not status.startswith((
            "ZERO_", "PAID_", "OPENROUTER_", "DUPLICATE_",
            "MODEL_", "NONZERO_", "GEMMA_",
        )):
            status = "GEMMA_PROBE_INVALID"
        print(json.dumps({"status": status}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
