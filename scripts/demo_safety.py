#!/usr/bin/env python3
"""Fail-closed safety preflight for OneCompany's disposable local demo."""

from __future__ import annotations

import argparse
import json

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def preflight(host: str, synthetic_data: bool, authority: bool) -> dict[str, object]:
    blockers = []
    if host not in LOCAL_HOSTS:
        blockers.append("non_local_host")
    if not synthetic_data:
        blockers.append("non_synthetic_data")
    if authority:
        blockers.append("authority_not_permitted")
    return {
        "safe": not blockers,
        "blockers": blockers,
        "scope": "LOCAL_DISPOSABLE_DEMO_ONLY",
        "deployable": False,
        "approved": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--synthetic-data", action="store_true")
    parser.add_argument("--authority", action="store_true")
    result = preflight(parser.parse_args().host, parser.parse_args().synthetic_data, parser.parse_args().authority)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["safe"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
