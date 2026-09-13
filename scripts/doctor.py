#!/usr/bin/env python3
"""Check whether a checkout has the prerequisites and coherent OneCompany control plane."""
from __future__ import annotations

import platform
import sys

from onecompany_lib import CONTROL, ROOT, command_exists, emergency_stop_active, load_json, run


def line(ok: bool, label: str, detail: str = "") -> None:
    print(f"[{'OK' if ok else '!!'}] {label}" + (f" — {detail}" if detail else ""))


def main() -> int:
    failures = 0
    python_ok = sys.version_info >= (3, 10); line(python_ok, "Python >= 3.10", platform.python_version()); failures += 0 if python_ok else 1
    for name, required in (("git", True), ("gh", False), ("node", False), ("npm", False)):
        exists = command_exists(name); line(exists, name, "required" if required else "optional/provider-dependent"); failures += 1 if required and not exists else 0
    for path in sorted(CONTROL.glob("*.json")):
        try: load_json(path); line(True, str(path.relative_to(ROOT)), "valid JSON")
        except Exception as exc: line(False, str(path.relative_to(ROOT)), str(exc)); failures += 1
    if command_exists("git"):
        result = run(["git", "rev-parse", "--is-inside-work-tree"]); line(result.returncode == 0, "Git worktree", result.stdout.strip() or result.stderr.strip()); failures += 0 if result.returncode == 0 else 1
    if command_exists("gh"):
        auth = run(["gh", "auth", "status"]); line(auth.returncode == 0, "GitHub CLI authentication", "authenticated" if auth.returncode == 0 else "not authenticated")
    try:
        config = load_json(CONTROL / "config.json"); actors = load_json(CONTROL / "actors.json"); readiness = {item.get("actor_id"): item for item in load_json(CONTROL / "readiness.json").get("actors", [])}
        line(not emergency_stop_active(config), "Emergency stop", "off" if not emergency_stop_active(config) else "ACTIVE — autonomous mutation is intentionally frozen")
        for actor in actors.get("actors", []):
            if not actor.get("enabled"): continue
            actor_id = actor.get("id"); status = readiness.get(actor_id, {}); verified = status.get("verified_capabilities", []); ok = actor.get("configured") and status.get("setup_state") in {"ready", "degraded"} and bool(verified)
            line(bool(ok), f"enabled actor {actor_id}", f"state={status.get('setup_state')} verified={','.join(verified) or 'none'}"); failures += 0 if ok else 1
    except Exception as exc: line(False, "actor/readiness summary", str(exc)); failures += 1
    print("\nDoctor result:", "READY" if failures == 0 else f"{failures} blocking problem(s)")
    print("Next: python onecompany.py validate && python onecompany.py status --live")
    return 0 if failures == 0 else 1


if __name__ == "__main__": sys.exit(main())
