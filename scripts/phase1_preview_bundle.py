#!/usr/bin/env python3
"""Compose local Phase-1 preview and quality evidence for one exact revision."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    """Load one trusted repository helper without adding package dependencies."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


preview = _load("local_preview_evidence", ROOT / "scripts" / "local_preview_evidence.py")
quality = _load("local_quality_evidence", ROOT / "scripts" / "local_quality_evidence.py")


def collect(revision: str, url: str) -> dict[str, object]:
    """Collect both local evidence classes and require exact revision agreement."""
    preview_evidence = preview.collect(revision, url)
    quality_evidence = quality.collect(revision)
    if preview_evidence.get("revision") != revision or quality_evidence.get("revision") != revision:
        raise ValueError("EXACT_REVISION_EVIDENCE_MISMATCH")
    if preview_evidence.get("health") != "PASS" or quality_evidence.get("status") != "PASS":
        raise ValueError("PHASE1_LOCAL_EVIDENCE_FAILED")
    return {
        "schema": "onecompany.phase1-local-evidence.v1",
        "revision": revision,
        "preview": preview_evidence,
        "quality": quality_evidence,
        "deployable": False,
        "authority_granted": False,
    }


def main() -> int:
    """Collect and print a non-deployable exact-revision local evidence bundle."""
    parser = argparse.ArgumentParser(description="Collect Phase-1 localhost preview and quality evidence")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    print(json.dumps(collect(args.revision, args.url), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
