#!/usr/bin/env python3
"""Deterministic, read-only accessibility-scan check (OC-P1-04 slice 8, #449).

Input: ``{"revision": 40-hex, "pages": [{"id", "violations": [{"rule", "impact", "nodes"}], "waived": [rule]}]}``.
Unwaived serious/critical violations and waivers that match nothing fail. minor/moderate are warnings.
No network, no writes, no clock.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HEX40 = re.compile(r"[0-9a-f]{40}")
IMPACTS = {"minor", "moderate", "serious", "critical"}
BLOCKING = {"serious", "critical"}


def load_pages(path: Path) -> list[dict]:
    """Return validated pages; raise ValueError on anything malformed."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"report unreadable: {path.name} ({exc.__class__.__name__})") from exc
    if not isinstance(data, dict):
        raise ValueError("report is not an object")
    revision = data.get("revision")
    if not isinstance(revision, str) or not HEX40.fullmatch(revision):
        raise ValueError("report needs a 40-hex revision")
    pages = data.get("pages")
    if not isinstance(pages, list) or not pages:
        raise ValueError("report has no non-empty pages list")
    seen: set[str] = set()
    for page in pages:
        if not isinstance(page, dict):
            raise ValueError("page is not an object")
        pid = page.get("id")
        if not isinstance(pid, str) or not pid.strip():
            raise ValueError("page needs a non-empty string id")
        if pid in seen:
            raise ValueError(f"duplicate page id: {pid}")
        seen.add(pid)
        violations = page.get("violations")
        waived = page.get("waived", [])
        if not isinstance(violations, list) or not isinstance(waived, list):
            raise ValueError(f"{pid} violations and waived must be lists")
        for v in violations:
            if not isinstance(v, dict):
                raise ValueError(f"{pid} violation is not an object")
            if not isinstance(v.get("rule"), str) or not v["rule"].strip():
                raise ValueError(f"{pid} violation needs a non-empty string rule")
            if not isinstance(v.get("impact"), str) or v["impact"] not in IMPACTS:
                raise ValueError(f"{pid} violation has unknown impact")
            nodes = v.get("nodes")
            if isinstance(nodes, bool) or not isinstance(nodes, int) or nodes < 1:
                raise ValueError(f"{pid} violation nodes must be an integer >= 1")
        for rule in waived:
            if not isinstance(rule, str) or not rule.strip():
                raise ValueError(f"{pid} waived entries must be non-empty strings")
    return pages


def evaluate(pages: list[dict]) -> dict:
    blocking: list[str] = []
    warnings: list[str] = []
    stale: list[str] = []
    for page in sorted(pages, key=lambda p: p["id"]):
        waived = set(page.get("waived", []))
        present = {v["rule"] for v in page["violations"]}
        for v in sorted(page["violations"], key=lambda x: x["rule"]):
            if v["impact"] in BLOCKING:
                if v["rule"] not in waived:
                    blocking.append(f"{page['id']} {v['rule']}")
            else:
                warnings.append(f"{page['id']} {v['rule']}")
        stale.extend(f"{page['id']} {rule}" for rule in sorted(waived - present))
    return {"pages": len(pages), "blocking": blocking, "warnings": warnings, "stale_waivers": stale}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only accessibility-scan check.")
    parser.add_argument("report", help="accessibility report JSON file")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    args = parser.parse_args(argv)
    try:
        result = evaluate(load_pages(Path(args.report)))
    except ValueError as exc:
        print(f"a11y-check: UNABLE TO VERIFY ({exc})", file=sys.stderr)
        return 2
    failed = bool(result["blocking"] or result["stale_waivers"])
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(f"a11y-check: {result['pages']} pages, {len(result['blocking'])} blocking, "
              f"{len(result['warnings'])} warnings, {len(result['stale_waivers'])} stale waivers")
        for item in result["blocking"]:
            print(f"  BLOCKING {item}")
        for item in result["stale_waivers"]:
            print(f"  STALE_WAIVER {item}")
        for item in result["warnings"]:
            print(f"  WARN {item}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
