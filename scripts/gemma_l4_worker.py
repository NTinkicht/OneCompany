#!/usr/bin/env python3
"""Bounded zero-additional-spend Gemma advisory worker for OneCompany."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import gemma_free_probe as guard  # noqa: E402

MAX_DIFF_BYTES = 60_000
MAX_FILE_BYTES = 8_000
MAX_REPO_FILES = 8
MAX_RESPONSE_BYTES = 64_000
SENSITIVE_PATH = re.compile(
    r"(^|/)(?:\.env(?:\.|$)|secrets?(?:/|$)|credentials?(?:/|$)|auth\.json$|"
    r".*\.(?:pem|key|p12|pfx|jks)$)",
    re.IGNORECASE,
)
SECRET_VALUE = re.compile(
    r"(?i)(?:api[_-]?key|token|secret|password|authorization)\s*[:=]\s*[^\s]{8,}"
)


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise ValueError("REPOSITORY_CONTEXT_UNAVAILABLE")
    return result.stdout


def safe_path(path: str) -> bool:
    return bool(path) and not SENSITIVE_PATH.search(path)


def task_tokens(task: str) -> set[str]:
    return {t for t in re.findall(r"[A-Za-z0-9_.-]{3,}", task.lower()) if len(t) >= 3}


def build_context(task: str, base_ref: str) -> dict:
    head_sha = git("rev-parse", "HEAD").strip()
    base_sha = git("merge-base", "HEAD", base_ref).strip()
    changed = [
        p for p in git("diff", "--name-only", f"{base_sha}...{head_sha}").splitlines()
        if p
    ]
    unsafe = [p for p in changed if not safe_path(p)]
    if unsafe:
        raise ValueError("SENSITIVE_REPOSITORY_PATH_BLOCKED")

    diff = git("diff", "--no-ext-diff", "--no-color", f"{base_sha}...{head_sha}")
    diff_bytes = len(diff.encode("utf-8"))
    if diff_bytes > MAX_DIFF_BYTES:
        raise ValueError("CONTEXT_INCOMPLETE_DIFF_OVERSIZED")
    if SECRET_VALUE.search(diff):
        raise ValueError("SECRET_LIKE_DIFF_CONTENT_BLOCKED")

    tokens = task_tokens(task)
    tracked = [p for p in git("ls-files").splitlines() if safe_path(p)]
    fixed = [
        "AGENTS.md",
        "agents/UNIVERSAL-CONTRACT.md",
        ".onecompany/budget.json",
    ]
    candidates = []
    seen = set()
    for path in fixed + tracked:
        if path in seen:
            continue
        seen.add(path)
        score = sum(1 for token in tokens if token in path.lower())
        if path in fixed:
            score += 100
        if path in changed:
            score += 50
        candidates.append((score, path))
    candidates.sort(key=lambda item: (-item[0], item[1]))

    files = []
    omitted = []
    for candidate_index, (_, rel) in enumerate(candidates):
        if len(files) >= MAX_REPO_FILES:
            omitted.append({
                "reason": "file_count_bound",
                "count": len(candidates) - candidate_index,
            })
            break
        path = ROOT / rel
        try:
            raw = path.read_bytes()
        except OSError:
            omitted.append({"path": rel, "reason": "read_error"})
            continue
        if b"\x00" in raw:
            omitted.append({"path": rel, "reason": "binary"})
            continue
        if len(raw) > MAX_FILE_BYTES:
            omitted.append({"path": rel, "reason": "file_exceeds_bound", "bytes": len(raw)})
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            omitted.append({"path": rel, "reason": "non_utf8"})
            continue
        if SECRET_VALUE.search(text):
            omitted.append({"path": rel, "reason": "secret_like_content"})
            continue
        files.append({"path": rel, "content": text})

    return {
        "head_sha": head_sha,
        "base_sha": base_sha,
        "changed_files": changed,
        "diff_bytes": diff_bytes,
        "diff": diff,
        "repository_files": files,
        "omitted_files": omitted,
    }


def request_gemma(key: str, task: str, context: dict, *, opener=None) -> str:
    guard.check_budget(ROOT / ".onecompany/budget.json")
    guard.check_model(guard.FREE_MODEL)
    if not key or not key.strip():
        raise ValueError("OPENROUTER_API_KEY_MISSING")
    if opener is None:
        opener = urllib.request.urlopen
    system_prompt = (ROOT / ".github/prompts/gemma-l4-worker.md").read_text(encoding="utf-8")
    payload = json.dumps(
        {
            "model": guard.FREE_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        {"task": task, "repository_evidence": context},
                        sort_keys=True,
                    ),
                },
            ],
            "usage": {"include": True},
            "temperature": 0,
            "stream": False,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        guard.API,
        data=payload,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/NTinkicht/OneCompany",
            "X-Title": "OneCompany bounded Gemma L4 worker",
        },
        method="POST",
    )
    try:
        with opener(req, timeout=120) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise ValueError(f"OPENROUTER_HTTP_{exc.code}") from None
    except urllib.error.URLError:
        raise ValueError("OPENROUTER_UNAVAILABLE") from None
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("OPENROUTER_RESPONSE_OVERSIZED")
    data = json.loads(body)
    usage = data.get("usage")
    if not isinstance(usage, dict) or type(usage.get("cost")) not in (int, float) or usage["cost"] != 0:
        raise ValueError("NONZERO_OR_UNKNOWN_INFERENCE_COST")
    choices = data.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise ValueError("OPENROUTER_CHOICES_INVALID")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ValueError("MODEL_OUTPUT_INVALID")
    return content


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True)
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        context = build_context(args.task, args.base_ref)
        result = request_gemma(os.environ.get("OPENROUTER_API_KEY", ""), args.task, context)
        args.output.write_text(result.rstrip() + "\n", encoding="utf-8")
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        status = str(exc) if isinstance(exc, ValueError) else "GEMMA_L4_WORKER_INVALID"
        print(json.dumps({"status": status}, sort_keys=True))
        return 2
    print(json.dumps({
        "status": "ADVISORY_RESULT_WRITTEN",
        "head_sha": context["head_sha"],
        "base_sha": context["base_sha"],
        "changed_files": len(context["changed_files"]),
        "omitted_files": len(context["omitted_files"]),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
