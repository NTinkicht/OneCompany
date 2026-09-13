#!/usr/bin/env python3
"""Prove a repository copied from the OneCompany template can be safely initialized once."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=str(cwd), text=True, capture_output=True, check=False)


def require(condition: bool, message: str) -> None:
    if not condition: raise AssertionError(message)


def main() -> int:
    try:
        with tempfile.TemporaryDirectory(prefix="onecompany-init-") as temp:
            target = Path(temp) / "template-copy"; target.mkdir()
            for name in (".onecompany", "scripts", "patterns", "overlays"):
                shutil.copytree(ROOT / name, target / name)
            shutil.copy2(ROOT / "onecompany.py", target / "onecompany.py")
            run(["git", "init", "-b", "main"], target); run(["git", "remote", "add", "origin", "https://github.com/example/template-copy.git"], target)
            initialized = run([sys.executable, "onecompany.py", "init", "--repository", "example/template-copy", "--project-name", "Template Copy", "--initialize-contracts"], target)
            require(initialized.returncode == 0, f"init failed:\n{initialized.stdout}\n{initialized.stderr}")
            config = json.loads((target / ".onecompany" / "config.json").read_text())
            queue = json.loads((target / ".onecompany" / "queue.json").read_text()); portfolio = json.loads((target / ".onecompany" / "portfolio.json").read_text()); catalog = json.loads((target / ".onecompany" / "requirements-catalog.json").read_text())
            state = json.loads((target / ".onecompany" / "state.json").read_text())
            require(config["project"]["repository"] == "example/template-copy", "init did not replace source repository")
            require(config["autonomy"]["level"] == "L1", "init must reset autonomy to L1")
            require(config["safety"]["emergency_stop"] is False, "init emergency-stop default mismatch")
            require(queue["work_units"] == [], "init must clear queue")
            require(portfolio["entities"] == [] and portfolio["links"] == [], "init must clear portfolio")
            require(catalog["requirements"] == [], "init must clear requirements")
            require(state["active_streams"] == [] and state["safe_start_candidates"] == [], "init must clear parallel flow state")
            require(json.loads((target / ".onecompany" / "ledger.json").read_text())["enabled"] is False, "init must disable ledger")
            require(json.loads((target / ".onecompany" / "supervision.json").read_text())["enabled"] is False, "init must disable supervision")
            for command in (["validate"], ["plan", "validate"], ["simulate-parallel"]):
                result = run([sys.executable, "onecompany.py", *command], target)
                require(result.returncode == 0, f"initialized target {' '.join(command)} failed:\n{result.stdout}\n{result.stderr}")
            second = run([sys.executable, "onecompany.py", "init", "--repository", "example/again"], target)
            require(second.returncode != 0, "init must refuse an already initialized company")
        print("OneCompany template-init smoke PASS"); return 0
    except AssertionError as exc:
        print(f"ERROR: {exc}"); return 1


if __name__ == "__main__": sys.exit(main())
