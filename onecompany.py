#!/usr/bin/env python3
"""Single dependency-free command entry point for a OneCompany checkout."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COMMANDS = {
    "onboard": ["onboard.py"],
    "doctor": ["doctor.py"], "status": ["status.py"], "check": ["check.py"], "validate": ["validate_all.py"], "schema-validate": ["schema_validate.py"],
    "simulate": ["simulate.py"], "simulate-ledger": ["simulate_ledger.py"], "simulate-supervision": ["simulate_supervision.py"], "simulate-parallel": ["simulate_parallelism.py"], "hardening-audit": ["hardening_audit.py"],
    "readiness": ["readiness.py"], "audit-github": ["github_audit.py"], "next-work": ["next_work.py"], "plan": ["planner.py"], "route": ["router.py"], "dispatch": ["dispatch.py"], "execute-dispatch": ["dispatch_execute_entry.py"],
    "ledger": ["ledger.py"], "lease": ["lease.py"], "gate": ["gate.py"], "merge": ["merge.py"], "reconcile": ["reconcile.py"], "supervise": ["supervise.py"], "handoff": ["handoff.py"], "handoff-runtime": ["handoff_runtime.py"],
    "bootstrap": ["bootstrap.py"], "init": ["init_project.py"],
    "assurance": ["assurance_gate.py"], "trace": ["assurance.py", "trace"], "risk": ["assurance.py", "risk"], "evidence": ["assurance.py", "evidence"],
    "verify-evidence": ["evidence_verify.py"], "attest": ["trusted_assurance.py"],
    "qualify": ["qualification.py"], "qualify-worker": ["qualification_executor.py"],
    "knowledge": ["knowledge.py"],
}


def usage() -> int:
    print("OneCompany 0.3.0")
    print("usage: python onecompany.py <command> [args]")
    print("\nStart here:")
    print("  onboard    assess a new/existing repository; read-only unless --apply")
    print("\nCommands:")
    for command in COMMANDS:
        if command != "onboard": print(f"  {command}")
    return 2


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help", "help"}: return usage()
    command = sys.argv[1]; spec = COMMANDS.get(command)
    if not spec:
        print(f"unknown command: {command}"); return usage()
    return subprocess.run([sys.executable, str(ROOT / "scripts" / spec[0]), *spec[1:], *sys.argv[2:]], cwd=str(ROOT), check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
