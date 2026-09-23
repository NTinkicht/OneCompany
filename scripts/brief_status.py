#!/usr/bin/env python3
"""Summarize a saved Product Brief without granting authority."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REQUIRED = ("problem", "audience", "outcome", "first_feature")


def summarize(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 128 * 1024:
        return {"stage": "BLOCKED", "blockers": ["unsafe_or_missing_brief"], "approved": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"stage": "BLOCKED", "blockers": ["malformed_brief"], "approved": False}
    if not isinstance(data, dict) or any(data.get(k) is True for k in ("approved", "deployment_authorized")):
        return {"stage": "BLOCKED", "blockers": ["authority_bearing_brief"], "approved": False}
    missing = [key for key in REQUIRED if not isinstance(data.get(key), str) or not data[key].strip()]
    return {
        "stage": "DRAFT_INCOMPLETE" if missing else "DRAFT_COMPLETE_NOT_APPROVED",
        "missing": missing,
        "blockers": [],
        "next_action": "collect_owner_answers" if missing else "request_explicit_owner_decision",
        "approved": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("brief", type=Path)
    result = summarize(parser.parse_args().brief)
    print(json.dumps(result, sort_keys=True))
    return 2 if result["stage"] == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
