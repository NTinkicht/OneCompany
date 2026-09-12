#!/usr/bin/env python3
"""Single dependency-free command entry point for a OneCompany checkout."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

COMMANDS = {
    "doctor": "doctor.py",
    "validate": "validate.py",
    "simulate": "simulate.py",
    "readiness": "readiness.py",
    "audit-github": "github_audit.py",
    "route": "router.py",
    "lease": "lease.py",
    "reconcile": "reconcile.py",
    "bootstrap": "bootstrap.py",
}


def usage() -> int:
    print("OneCompany 0.1.0-foundation")
    print("usage: python onecompany.py <command> [args]")
    print("commands:")
    for command in COMMANDS:
        print(f"  {command}")
    return 2


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help", "help"}:
        return usage()
    command = sys.argv[1]
    script = COMMANDS.get(command)
    if not script:
        print(f"unknown command: {command}")
        return usage()
    completed = subprocess.run([sys.executable, str(ROOT / "scripts" / script), *sys.argv[2:]], cwd=str(ROOT), check=False)
    return completed.returncode


if __name__ == "__main__":
    sys.exit(main())
