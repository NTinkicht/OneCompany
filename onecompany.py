#!/usr/bin/env python3
"""Single dependency-free command entry point for a OneCompany checkout."""
from __future__ import annotations

import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COMMANDS = {
    "start": ["first_run_wizard.py"],
    "onboard": ["onboard.py"],
    "brief": ["product_brief.py"],
    "brief-handoff": ["brief_handoff_proposal.py"],
    "journey": ["first_run_journey.py"],
    "demo": ["phase1_vertical_smoke.py"],
    "preview-local": ["../examples/vertical-slice/app.py"],
    "mission-control": ["mission_control_local.py"],
    "shadow-migration": ["shadow_migration.py"],
    "cutover-readiness": ["cutover_readiness.py"],
    "doctor": ["doctor.py"], "status": ["status.py"], "check": ["check.py"], "validate": ["validate_all.py"], "schema-validate": ["schema_validate.py"],
    "simulate": ["simulate.py"], "simulate-ledger": ["simulate_ledger.py"], "simulate-supervision": ["simulate_supervision.py"], "simulate-parallel": ["simulate_parallelism.py"], "hardening-audit": ["hardening_audit.py"],
    "readiness": ["readiness.py"], "audit-github": ["github_audit.py"], "next-work": ["next_work.py"], "plan": ["planner.py"], "route": ["router.py"], "dispatch": ["dispatch.py"], "execute-dispatch": ["dispatch_execute_entry.py"],
    "ledger": ["ledger.py"], "lease": ["lease.py"], "gate": ["gate.py"], "merge": ["merge.py"], "reconcile": ["reconcile.py"], "supervise": ["supervise.py"], "handoff": ["handoff.py"], "handoff-runtime": ["handoff_runtime.py"],
    "execution": ["execution.py"],
    "bootstrap": ["bootstrap.py"], "init": ["init_project.py"],
    "assurance": ["assurance_gate.py"], "trace": ["assurance.py", "trace"], "risk": ["assurance.py", "risk"], "evidence": ["assurance.py", "evidence"],
    "verify-evidence": ["evidence_verify.py"], "attest": ["trusted_assurance.py"],
    "qualify": ["qualification.py"], "qualify-worker": ["qualification_executor.py"],
    "knowledge": ["knowledge.py"],
}


def usage() -> int:
    """Print available commands and highlight the safe first-run route."""
    print("OneCompany 0.3.0")
    print("usage: python onecompany.py <command> [args]")
    print("\nStart here:")
    print("  start             guided Create/Adopt owner Product Brief (source checkout)")
    print("  onboard           assess a new/existing repository; read-only unless --apply")
    print("  brief             draft Product Brief from owner answers; read-only unless --save-to")
    print("  brief-handoff     preview a read-only planning handoff from a saved owner brief")
    print("  journey           guided Create/Adopt next steps; read-only, never approval")
    print("  demo              run real disposable local CRUD proof from owner draft (source checkout)")
    print("  preview-local     interact with disposable checklist UI at localhost (source checkout)")
    print("  mission-control   serve canonical read-only Mission Control evidence at localhost")
    print("  shadow-migration  analyze an external migration snapshot without target mutation")
    print("  cutover-readiness prove quiescent C2b readiness without target mutation")
    print("\nCommands:")
    featured = {"start", "onboard", "brief", "brief-handoff", "journey", "demo", "preview-local", "mission-control", "shadow-migration", "cutover-readiness"}
    for command in COMMANDS:
        if command not in featured:
            print(f"  {command}")
    return 2


def main() -> int:
    """Route the selected subcommand without changing customer project authority."""
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help", "help"}:
        return usage()
    command = sys.argv[1]
    spec = COMMANDS.get(command)
    if not spec:
        print(f"unknown command: {command}")
        return usage()
    helper = ROOT / "scripts" / spec[0]
    interactive_source = {"start", "demo", "preview-local", "mission-control"}
    if command in interactive_source and not helper.is_file():
        print(f"{command} is available from the OneCompany source checkout only; no target is modified.")
        return 2
    argv = [sys.executable, str(helper), *spec[1:], *sys.argv[2:]]
    if command in {"preview-local", "mission-control"}:
        child = subprocess.Popen(argv, cwd=str(ROOT))

        def stop_child(signum, _frame):
            if child.poll() is None:
                child.send_signal(signum)

        previous_term = signal.signal(signal.SIGTERM, stop_child)
        try:
            return child.wait()
        except KeyboardInterrupt:
            if child.poll() is None:
                child.send_signal(signal.SIGINT)
            try:
                return child.wait(timeout=6)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=3)
                return 130
        finally:
            signal.signal(signal.SIGTERM, previous_term)
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=6)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=3)
    return subprocess.run(argv, cwd=str(ROOT), check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
