#!/usr/bin/env python3
"""Run the deterministic local OneCompany foundation acceptance suite."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

STEPS = [
    ("Validate control plane", [sys.executable, "onecompany.py", "validate"]),
    ("Simulate core invariants", [sys.executable, "onecompany.py", "simulate"]),
    ("Simulate durable ledger", [sys.executable, "onecompany.py", "simulate-ledger"]),
    ("Simulate supervision", [sys.executable, "onecompany.py", "simulate-supervision"]),
    ("Smoke fresh bootstrap", [sys.executable, "scripts/smoke_bootstrap.py"]),
    ("Smoke template initialization", [sys.executable, "scripts/smoke_init.py"]),
    ("Compile Python helpers", [sys.executable, "-m", "compileall", "-q", "scripts"]),
]


def main() -> int:
    failed: list[str] = []
    for label, command in STEPS:
        print(f"\n== {label} ==")
        result = subprocess.run(command, cwd=str(ROOT), check=False)
        if result.returncode != 0:
            failed.append(label)
    if failed:
        print("\nOneCompany CHECK FAILED:")
        for label in failed:
            print(f"- {label}")
        return 1
    print("\nOneCompany CHECK PASS — deterministic foundation acceptance is green.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
