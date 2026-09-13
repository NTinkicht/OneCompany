#!/usr/bin/env python3
"""Mechanically enforce trusted-kernel import direction.

Trusted authority modules may use the Python standard library and other modules
explicitly listed in the kernel boundary. They may not depend on userspace or
on an unlisted local control-plane helper: adding such a dependency requires an
explicit, reviewable expansion of the trusted boundary.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

from onecompany_lib import CONTROL, ROOT

POLICY_PATH = CONTROL / "kernel-boundary.json"
SCRIPTS = ROOT / "scripts"


def _imports(path: Path) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                values.append((alias.name.split(".", 1)[0], node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                values.append(("<relative>", node.lineno))
            elif node.module:
                values.append((node.module.split(".", 1)[0], node.lineno))
    return values


def boundary_errors(policy_path: Path = POLICY_PATH, scripts_dir: Path = SCRIPTS) -> list[str]:
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"cannot load kernel boundary policy: {exc}"]
    trusted = {str(value) for value in policy.get("trusted_modules", []) if value}
    forbidden = {str(value) for value in policy.get("forbidden_repo_import_roots", []) if value}
    if not trusted:
        return ["kernel boundary has no trusted_modules"]
    local_scripts = {path.stem for path in scripts_dir.glob("*.py")}
    errors: list[str] = []
    for module in sorted(trusted):
        path = scripts_dir / f"{module}.py"
        if not path.is_file():
            errors.append(f"trusted kernel module is missing: scripts/{module}.py")
            continue
        try:
            imports = _imports(path)
        except (OSError, SyntaxError) as exc:
            errors.append(f"cannot parse trusted kernel module {module}: {exc}")
            continue
        for root, line in imports:
            if root == "<relative>":
                errors.append(f"{module}:{line}: relative import is forbidden in trusted kernel")
            elif root in forbidden:
                errors.append(f"{module}:{line}: trusted kernel imports forbidden userspace root {root}")
            elif root in local_scripts and root not in trusted:
                errors.append(f"{module}:{line}: trusted kernel imports unlisted local module {root}")
    return errors


def main() -> int:
    errors = boundary_errors()
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("Trusted-kernel import boundary PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
