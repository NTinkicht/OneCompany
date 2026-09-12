#!/usr/bin/env python3
"""Prove a fresh OneCompany bootstrap creates a clean target company."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=str(cwd or ROOT), text=True, capture_output=True, check=False)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    try:
        with tempfile.TemporaryDirectory(prefix="onecompany-bootstrap-") as temp:
            target = Path(temp) / "acme-product"
            target.mkdir()

            init = run(["git", "init", "-b", "main"], target)
            require(init.returncode == 0, init.stderr or "git init failed")
            remote = run(["git", "remote", "add", "origin", "https://github.com/example/acme-product.git"], target)
            require(remote.returncode == 0, remote.stderr or "git remote add failed")

            install = run([
                sys.executable,
                str(ROOT / "onecompany.py"),
                "bootstrap",
                "--target", str(target),
                "--repository", "example/acme-product",
                "--project-name", "Acme Product",
                "--default-branch", "main",
                "--initialize-contracts",
            ])
            require(install.returncode == 0, f"bootstrap failed:\n{install.stdout}\n{install.stderr}")

            config = json.loads((target / ".onecompany" / "config.json").read_text(encoding="utf-8"))
            queue = json.loads((target / ".onecompany" / "queue.json").read_text(encoding="utf-8"))
            state = json.loads((target / ".onecompany" / "state.json").read_text(encoding="utf-8"))

            require(config["project"]["name"] == "Acme Product", "bootstrap leaked source project name")
            require(config["project"]["repository"] == "example/acme-product", "bootstrap leaked source repository identity")
            require(config["project"]["default_branch"] == "main", "bootstrap default branch mismatch")
            require(queue.get("work_units") == [], "fresh target queue must start empty")
            require(state.get("current_work_unit") is None, "fresh target inherited a source WU")
            require(state.get("current_pr") is None, "fresh target inherited a source PR")
            require(state.get("current_material_authors") == [], "fresh target inherited source authorship")
            require(state.get("active_leases") == [], "fresh target inherited source leases")

            for contract in ("PRODUCT.md", "ARCHITECTURE.md", "SECURITY.md", "QUALITY.md", "OPERATIONS.md"):
                require((target / contract).exists(), f"missing initialized contract {contract}")

            for command in (["validate"], ["simulate"], ["simulate-supervision"], ["next-work"]):
                result = run([sys.executable, str(target / "onecompany.py"), *command], target)
                require(result.returncode == 0, f"target {' '.join(command)} failed:\n{result.stdout}\n{result.stderr}")

            second = run([
                sys.executable,
                str(ROOT / "onecompany.py"),
                "bootstrap",
                "--target", str(target),
                "--repository", "example/acme-product",
            ])
            require(second.returncode != 0, "bootstrap must refuse an existing .onecompany installation")

        print("OneCompany bootstrap smoke PASS")
        return 0
    except AssertionError as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
