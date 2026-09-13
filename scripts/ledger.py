#!/usr/bin/env python3
"""Inspect or append trusted events to the OneCompany durable GitHub ledger."""
from __future__ import annotations

import argparse
import json
import sys

from ledger_lib import derive, list_events, post_event


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    read = sub.add_parser("read")
    read.add_argument("--pr", type=int)
    read.add_argument("--events", action="store_true", help="Include trusted raw events")

    post = sub.add_parser("post")
    post.add_argument("--type", required=True)
    post.add_argument("--actor", required=True)
    post.add_argument("--payload-json", default="{}")

    args = parser.parse_args()
    try:
        if args.command == "read":
            events = list_events()
            payload = {"derived": derive(events, args.pr)}
            if args.events:
                payload["events"] = events
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return 0
        payload = json.loads(args.payload_json)
        if not isinstance(payload, dict):
            raise ValueError("payload must be a JSON object")
        event = post_event(args.type, args.actor, payload)
        print(json.dumps(event, indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
