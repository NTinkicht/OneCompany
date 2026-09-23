#!/usr/bin/env python3
"""Read-only Product Brief answer diff; neither input grants authority."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

MAX_BYTES = 16_384
FIELDS = ("audience", "problem", "outcome", "first_feature", "constraints")


def load(path: Path) -> dict:
    if path.is_symlink(): raise ValueError("brief path must not be a symlink")
    if not path.is_file() or path.stat().st_size > MAX_BYTES: raise ValueError("brief must be a regular bounded file")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != "1.0" or data.get("document_kind") != "product_brief_draft" or data.get("status") != "DRAFT_NOT_APPROVED":
        raise ValueError("unsupported Product Brief draft")
    if data.get("approval") != {"product_brief": False, "implementation": False, "deployment": False} or data.get("write_lease_granted") is not False:
        raise ValueError("brief contains authority or malformed approval state")
    if not isinstance(data.get("answers"), dict): raise ValueError("brief answers are missing")
    return data


def compare(before: dict, after: dict) -> dict:
    changes = []
    for field in FIELDS:
        old, new = before["answers"].get(field), after["answers"].get(field)
        if old != new: changes.append({"field": field, "before": old, "after": new})
    return {"status": "PREVIEW_ONLY_NOT_APPROVED", "changed_fields": changes, "implementation_authorized": False, "next_action": "Owner reviews these draft changes; use the trusted planning process before any implementation."}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Preview changes between two unapproved Product Brief drafts")
    p.add_argument("before", type=Path); p.add_argument("after", type=Path); p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    try:
        result = compare(load(a.before), load(a.after))
        if a.json: print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("OneCompany Product Brief change preview - NOT APPROVED")
            if not result["changed_fields"]: print("No owner-answer changes.")
            for item in result["changed_fields"]: print(f"{item['field']}: {item['before']!r} -> {item['after']!r}")
            print("Next: " + result["next_action"])
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("REFUSED: " + str(exc), file=sys.stderr); return 2

if __name__ == "__main__": sys.exit(main())
