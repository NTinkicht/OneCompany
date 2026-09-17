#!/usr/bin/env python3
"""Prove a fresh OneCompany bootstrap creates a clean, self-contained target company."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(
    command: list[str], cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd or ROOT),
        text=True,
        capture_output=True,
        check=False,
    )


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    try:
        with tempfile.TemporaryDirectory(prefix="onecompany-bootstrap-") as temp:
            target = Path(temp) / "acme-product"
            target.mkdir()
            (target / "tests").mkdir()
            (target / "tests" / "product_test.py").write_text("# product-owned\n")
            (target / "examples").mkdir()
            (target / "examples" / "product.txt").write_text("product-owned\n")
            require(
                run(["git", "init", "-b", "main"], target).returncode == 0,
                "git init failed",
            )
            require(
                run(
                    [
                        "git",
                        "remote",
                        "add",
                        "origin",
                        "https://github.com/example/acme-product.git",
                    ],
                    target,
                ).returncode
                == 0,
                "git remote add failed",
            )
            install = run(
                [
                    sys.executable,
                    str(ROOT / "onecompany.py"),
                    "bootstrap",
                    "--target",
                    str(target),
                    "--repository",
                    "example/acme-product",
                    "--project-name",
                    "Acme Product",
                    "--default-branch",
                    "main",
                    "--code-owner",
                    "@example/reviewers",
                    "--root-principal",
                    "example-admin",
                    "--initialize-contracts",
                ]
            )
            require(
                install.returncode == 0,
                f"bootstrap failed:\n{install.stdout}\n{install.stderr}",
            )
            config = json.loads(
                (target / ".onecompany" / "config.json").read_text()
            )
            queue = json.loads((target / ".onecompany" / "queue.json").read_text())
            state = json.loads((target / ".onecompany" / "state.json").read_text())
            ledger = json.loads((target / ".onecompany" / "ledger.json").read_text())
            supervision = json.loads(
                (target / ".onecompany" / "supervision.json").read_text()
            )
            portfolio = json.loads(
                (target / ".onecompany" / "portfolio.json").read_text()
            )
            catalog = json.loads(
                (target / ".onecompany" / "requirements-catalog.json").read_text()
            )
            identity = json.loads(
                (target / ".onecompany" / "identity.json").read_text()
            )
            codeowners = (target / ".github" / "CODEOWNERS").read_text()
            roots = [
                item
                for item in identity.get("principals", [])
                if "root" in item.get("authorities", [])
            ]
            require(
                config["project"]["name"] == "Acme Product",
                "bootstrap leaked source project name",
            )
            require(
                config["project"]["repository"] == "example/acme-product",
                "bootstrap leaked source repository identity",
            )
            require(
                config["project"]["default_branch"] == "main",
                "bootstrap default branch mismatch",
            )
            require(
                roots and roots[0].get("login") == "example-admin",
                "bootstrap did not bind explicit human root principal",
            )
            require(
                "@example/reviewers" in codeowners and "@NTinkicht" not in codeowners,
                "bootstrap did not rebind CODEOWNERS",
            )
            require(
                config.get("safety", {}).get("emergency_stop") is False,
                "fresh company must not start in emergency stop",
            )
            require(
                ledger.get("enabled") is False,
                "fresh company inherited source durable-ledger activation",
            )
            require(
                ledger.get("issue_number") is None,
                "fresh company inherited source Team Room issue number",
            )
            require(
                ledger.get("trusted_publisher_logins") == [],
                "fresh company inherited source trusted ledger publishers",
            )
            require(
                supervision.get("enabled") is False
                and supervision.get("mode") == "observe_only",
                "fresh company inherited active supervision",
            )
            require(
                supervision.get("coordination", {}).get("team_room_issue_number") is None,
                "fresh company inherited source supervision Team Room binding",
            )
            require(
                supervision.get("github_actions", {}).get("may_post_team_room") is False
                and supervision.get("github_actions", {}).get("may_failover") is False
                and supervision.get("github_actions", {}).get("may_merge") is False,
                "fresh company inherited autonomous supervisor authority",
            )
            require(
                supervision.get("chatgpt_tasks", {}).get("may_mutate") is False,
                "fresh company inherited scheduled mutation authority",
            )
            require(queue.get("work_units") == [], "fresh target queue must start empty")
            require(
                portfolio.get("entities") == [] and portfolio.get("links") == [],
                "fresh target portfolio must start empty",
            )
            require(
                catalog.get("requirements") == [],
                "fresh target requirements catalog must start empty",
            )
            require(
                state.get("active_streams") == []
                and state.get("safe_start_candidates") == [],
                "fresh target inherited flow state",
            )
            require(
                (target / "tests" / "product_test.py").read_text()
                == "# product-owned\n",
                "bootstrap overwrote product tests",
            )
            require(
                (target / "examples" / "product.txt").read_text()
                == "product-owned\n",
                "bootstrap overwrote product examples",
            )
            require(
                not (target / "source-evidence" / "tabibi").exists(),
                "fresh company inherited source-only Tabibi migration evidence",
            )
            require(
                (target / ".onecompany" / "selftest" / "test_planning.py").exists(),
                "framework self-tests not installed",
            )
            require(
                (
                    target
                    / ".onecompany"
                    / "reference"
                    / "assurance"
                    / "WU900.json"
                ).exists(),
                "framework assurance fixture not installed",
            )
            for contract in (
                "PRODUCT.md",
                "ARCHITECTURE.md",
                "SECURITY.md",
                "QUALITY.md",
                "DESIGN.md",
                "OPERATIONS.md",
            ):
                require((target / contract).exists(), f"missing initialized contract {contract}")
            for command in (
                ["validate"],
                ["plan", "validate"],
                ["simulate"],
                ["simulate-ledger"],
                ["simulate-parallel"],
                ["simulate-supervision"],
                ["next-work"],
            ):
                result = run(
                    [sys.executable, str(target / "onecompany.py"), *command],
                    target,
                )
                require(
                    result.returncode == 0,
                    f"target {' '.join(command)} failed:\n{result.stdout}\n{result.stderr}",
                )
            selftest = run(
                [
                    sys.executable,
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    ".onecompany/selftest",
                    "-p",
                    "test_*.py",
                ],
                target,
            )
            require(
                selftest.returncode == 0,
                f"target framework self-tests failed:\n{selftest.stdout}\n{selftest.stderr}",
            )
            second = run(
                [
                    sys.executable,
                    str(ROOT / "onecompany.py"),
                    "bootstrap",
                    "--target",
                    str(target),
                    "--repository",
                    "example/acme-product",
                    "--code-owner",
                    "@example/reviewers",
                    "--root-principal",
                    "example-admin",
                ]
            )
            require(
                second.returncode != 0,
                "bootstrap must refuse an existing .onecompany installation",
            )
        print("OneCompany bootstrap smoke PASS")
        return 0
    except AssertionError as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
