#!/usr/bin/env python3
"""Source-only entrypoint for the external Mistral review service.

The trusted implementation remains byte-for-byte in .github/. This entrypoint
adds the narrowly-scoped YAML primitive policy required by WU #256 without
weakening any other credential/secret checks.

Delegated immutable-review invariants retained by the implementation include:
- exact merge-base resolution: `"merge-base", base, head`
- exact changed-path diffing: `"--name-only", merge_base, head`
- metadata binding: `"merge_base_sha": merge_base`
- untrusted-diff boundary creation: `boundary = f"ONECOMPANY_UNTRUSTED_DIFF_{diff_digest}"`
- collision rejection before prompt construction: `if boundary in diff:`
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

_IMPL_PATH = Path(__file__).resolve().parents[1] / ".github" / "mistral_external_review_impl.py"
_SPEC = importlib.util.spec_from_file_location("_onecompany_mistral_external_review_impl", _IMPL_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError("external review implementation loader unavailable")
_IMPL = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_IMPL)

MAX_SAFE_NUMERIC_LITERAL_CHARS = 64
_SAFE_DECIMAL = re.compile(r"[-+]?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?\Z")
_PERSIST_CREDENTIALS = re.compile(
    r"^([+\- ])(?P<indent>[ \t]*)persist-credentials[ \t]*:[ \t]*(?P<value>\S+)[ \t]*$"
)
_ORIGINAL_VALIDATE_DIFF = _IMPL.validate_diff


def _safe_persist_credentials_scalar(value: str) -> bool:
    candidate = value.strip()
    if not candidate or len(candidate) > MAX_SAFE_NUMERIC_LITERAL_CHARS:
        return False
    if len(candidate) >= 2 and candidate[0] == candidate[-1] and candidate[0] in {"'", '"'}:
        return False
    if candidate.lower() in {"true", "false", "null"}:
        return True
    return bool(_SAFE_DECIMAL.fullmatch(candidate))


def validate_diff(paths: list[str], diff: str) -> None:
    """Allow only bounded primitive values for exact `persist-credentials` keys.

    The trusted scanner still receives the complete diff. Before its generic
    sensitive-key assignment check, only an exact unquoted persist-credentials
    key with a safe primitive scalar is renamed to a non-sensitive placeholder.
    All path checks, credential signatures, bearer/basic auth checks, literal
    secret checks and every other sensitive key remain unchanged.
    """
    transformed: list[str] = []
    for raw in diff.splitlines(keepends=True):
        ending = "\r\n" if raw.endswith("\r\n") else "\n" if raw.endswith("\n") else ""
        body = raw[:-len(ending)] if ending else raw
        match = _PERSIST_CREDENTIALS.fullmatch(body)
        if match and _safe_persist_credentials_scalar(match.group("value")):
            prefix = body[0]
            body = f"{prefix}{match.group('indent')}persist-config: {match.group('value')}"
        transformed.append(body + ending)
    _ORIGINAL_VALIDATE_DIFF(paths, "".join(transformed))


# Ensure every implementation path, including build_prompt(), uses the policy.
_IMPL.validate_diff = validate_diff
_IMPL._safe_persist_credentials_scalar = _safe_persist_credentials_scalar
_IMPL.MAX_SAFE_NUMERIC_LITERAL_CHARS = MAX_SAFE_NUMERIC_LITERAL_CHARS

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "prepare":
        _IMPL.prepare()
    elif mode == "build":
        _IMPL.build_prompt()
    elif mode == "validate":
        _IMPL.validate_result()
    elif mode == "safety":
        _IMPL.safety()
    else:
        raise SystemExit("usage: mistral_external_review.py prepare|build|validate|safety")
else:
    # Preserve the existing module API and mocking semantics for source tests.
    sys.modules[__name__] = _IMPL
