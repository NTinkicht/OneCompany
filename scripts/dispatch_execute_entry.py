#!/usr/bin/env python3
"""A3b execute-dispatch entrypoint with reviewed automatic adapters."""
from __future__ import annotations

import argparse
import json
import sys
from typing import Callable

import copilot_actions_adapter
import dispatch_execute
import local_actions_adapter
import fixture_actions_adapter

AutomaticAdapter = Callable[[dict], dict]
ADAPTERS: dict[str, AutomaticAdapter] = {
    copilot_actions_adapter.MECHANISM_ID: copilot_actions_adapter.invoke,
    local_actions_adapter.MECHANISM_ID: local_actions_adapter.invoke,
    fixture_actions_adapter.MECHANISM_ID: fixture_actions_adapter.invoke,
}


def _option_value(argv: list[str], name: str) -> str | None:
    """Read one CLI option without changing A3a parsing for other mechanisms."""
    for index, value in enumerate(argv):
        if value == name and index + 1 < len(argv):
            return argv[index + 1]
        prefix = name + "="
        if value.startswith(prefix):
            return value[len(prefix) :]
    return None


def _automatic_main(adapter: AutomaticAdapter) -> int:
    """Execute one exact reviewed automatic mechanism through the A3a contract."""
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

    result = dispatch_execute.execute_with_adapter(request, adapter)
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") in {
        "DISPATCH_STARTED",
        "DISPATCH_ALREADY_ACTIVE",
        "DISPATCH_COMPLETED",
    } else 2


def main() -> int:
    """Delegate legacy mechanisms unchanged and select only reviewed A3b adapters."""
    mechanism = _option_value(sys.argv[1:], "--mechanism")
    adapter = ADAPTERS.get(str(mechanism or ""))
    if adapter is None:
        return dispatch_execute.main()
    return _automatic_main(adapter)


if __name__ == "__main__":
    sys.exit(main())
