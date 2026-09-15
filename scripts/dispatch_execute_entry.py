#!/usr/bin/env python3
"""A3b execute-dispatch entrypoint with one reviewed automatic adapter."""
from __future__ import annotations

import argparse
import json
import sys

import copilot_actions_adapter
import dispatch_execute


def _option_value(argv: list[str], name: str) -> str | None:
    """Read one CLI option without changing A3a parsing for other mechanisms."""
    for index, value in enumerate(argv):
        if value == name and index + 1 < len(argv):
            return argv[index + 1]
        prefix = name + "="
        if value.startswith(prefix):
            return value[len(prefix) :]
    return None


def _copilot_main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--actor", required=True)
    parser.add_argument("--capability", required=True)
    parser.add_argument("--mechanism", required=True)
    parser.add_argument("--work-unit", required=True)
    parser.add_argument("--lease-id")
    parser.add_argument("--unattended", action="store_true")
    args = parser.parse_args()

    request, blocked = dispatch_execute.build_execution_request(args)
    if request is None:
        print(json.dumps(blocked, indent=2))
        return 2

    result = dispatch_execute.execute_with_adapter(
        request,
        copilot_actions_adapter.invoke,
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") in {
        "DISPATCH_STARTED",
        "DISPATCH_ALREADY_ACTIVE",
        "DISPATCH_COMPLETED",
    } else 2


def main() -> int:
    """Delegate all legacy mechanisms unchanged; handle only the exact A3b mechanism."""
    mechanism = _option_value(sys.argv[1:], "--mechanism")
    if mechanism != copilot_actions_adapter.MECHANISM_ID:
        return dispatch_execute.main()
    return _copilot_main()


if __name__ == "__main__":
    sys.exit(main())
