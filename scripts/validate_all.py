#!/usr/bin/env python3
"""Run all dependency-free OneCompany validators."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    validators = [
        "validate.py",
        "governance_validate.py",
        "dispatch_validate.py",
        "ledger_validate.py",
        "supervision_validate.py",
        "hardening_audit.py",
    ]
    failed = False
    for name in validators:
        result = subprocess.run([sys.executable, str(ROOT / name)], cwd=str(ROOT.parent), check=False)
        if result.returncode != 0:
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
