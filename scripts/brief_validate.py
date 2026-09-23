#!/usr/bin/env python3
"""Read-only validation for an explicitly saved Product Brief JSON file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REQUIRED = ("problem", "audience", "outcome", "first_feature")
FORBIDDEN_AUTHORITY = ("approved", "approval", "lease", "write_lease", "deployment_authorized")
MAX_BYTES = 128 * 1024


def validate(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        return {"valid": False, "status": "REFUSED_UNSAFE_PATH"}
    if path.stat().st_size > MAX_BYTES:
        return {"valid": False, "status": "REFUSED_OVERSIZED"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {"valid": False, "status": "REFUSED_MALFORMED"}
    if not isinstance(data, dict):
        return {"valid": False, "status": "REFUSED_WRONG_KIND"}
    if any(data.get(key) not in (None, False, "", "NOT_GRANTED") for key in FORBIDDEN_AUTHORITY):
        return {"valid": False, "status": "REFUSED_AUTHORITY_BEARING"}
    missing = [key for key in REQUIRED if not isinstance(data.get(key), str) or not data[key].strip()]
    return {
        "valid": not missing,
        "status": "PROPOSAL_READY_NOT_APPROVED" if not missing else "INCOMPLETE_NOT_APPROVED",
        "missing": missing,
        "approved": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("brief", type=Path)
    args = parser.parse_args()
    result = validate(args.brief)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
