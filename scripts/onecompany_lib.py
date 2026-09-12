#!/usr/bin/env python3
"""Shared dependency-free helpers for OneCompany tooling."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTROL = ROOT / ".onecompany"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, value: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.replace(tmp, path)


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def run(command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd or ROOT),
        check=False,
        text=True,
        capture_output=True,
    )


def autonomy_number(level: str) -> int:
    if len(level) == 2 and level.startswith("L") and level[1].isdigit():
        return int(level[1])
    raise ValueError(f"invalid autonomy level: {level}")


def active_implementation_leases(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        lease
        for lease in state.get("active_leases", [])
        if lease.get("status") == "active" and lease.get("role") == "implementation"
    ]


def budget_allows(cost_class: str, budget: dict[str, Any]) -> bool:
    classes = budget.get("cost_classes", {})
    if cost_class in classes.get("allowed", []):
        return True
    if cost_class in classes.get("forbidden", []):
        return False
    if cost_class in classes.get("conditionally_allowed", []):
        return budget.get("ai", {}).get("additional_monthly_spend_cap", 0) > 0
    return budget.get("ai", {}).get("unknown_cost_behavior") == "allow_within_cap"


def github_repo_from_config(config: dict[str, Any]) -> str | None:
    value = config.get("project", {}).get("repository")
    return value if isinstance(value, str) and "/" in value else None
