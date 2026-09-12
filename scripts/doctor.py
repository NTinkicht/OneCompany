#!/usr/bin/env python3
"""Check whether the local environment can operate a OneCompany repository."""
from __future__ import annotations

import platform
import sys

from onecompany_lib import CONTROL, ROOT, command_exists, load_json, run


def line(ok: bool, label: str, detail: str = "") -> None:
    mark = "OK" if ok else "!!"
    suffix = f" — {detail}" if detail else ""
    print(f"[{mark}] {label}{suffix}")


def main() -> int:
    failures = 0
    line(sys.version_info >= (3, 10), "Python >= 3.10", platform.python_version())
    if sys.version_info < (3, 10):
        failures += 1

    for name, required in (("git", True), ("gh", False), ("node", False), ("npm", False)):
        exists = command_exists(name)
        line(exists, name, "required" if required else "optional/provider-dependent")
        if required and not exists:
            failures += 1

    control_files = (
        "config.json",
        "actors.json",
        "roles.json",
        "budget.json",
        "state.json",
        "queue.json",
        "patterns.json",
        "overlays.json",
        "readiness.json",
    )
    for relative in control_files:
        path = CONTROL / relative
        try:
            load_json(path)
            line(True, str(path.relative_to(ROOT)), "valid JSON")
        except Exception as exc:
            line(False, str(path.relative_to(ROOT)), str(exc))
            failures += 1

    if command_exists("git"):
        result = run(["git", "rev-parse", "--is-inside-work-tree"])
        line(result.returncode == 0, "Git worktree", result.stdout.strip() or result.stderr.strip())

    if command_exists("gh"):
        auth = run(["gh", "auth", "status"])
        line(auth.returncode == 0, "GitHub CLI authentication", "authenticated" if auth.returncode == 0 else "not authenticated")

    try:
        actors = load_json(CONTROL / "actors.json")
        readiness = {item.get("actor_id"): item for item in load_json(CONTROL / "readiness.json").get("actors", [])}
        for actor in actors.get("actors", []):
            if not actor.get("enabled"):
                continue
            actor_id = actor.get("id")
            status = readiness.get(actor_id, {})
            verified = status.get("verified_capabilities", [])
            ok = actor.get("configured") and status.get("setup_state") in {"ready", "degraded"} and bool(verified)
            line(bool(ok), f"enabled actor {actor_id}", f"state={status.get('setup_state')} verified={','.join(verified) or 'none'}")
            if not ok:
                failures += 1
    except Exception as exc:
        line(False, "actor readiness summary", str(exc))
        failures += 1

    print("\nDoctor result:", "READY" if failures == 0 else f"{failures} blocking problem(s)")
    print("Next: python onecompany.py readiness --local-probe")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
