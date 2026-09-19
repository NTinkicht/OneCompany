#!/usr/bin/env python3
"""Reject bundled client operating evidence from reusable product distributions."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for name in ("source-evidence", "evidence"):
    if (ROOT / name).exists():
        raise SystemExit(f"client-specific evidence must not ship with OneCompany: {name}")
print("PASS: no root-level client operating evidence")
