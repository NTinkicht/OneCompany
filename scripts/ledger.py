#!/usr/bin/env python3
"""Inspect or append trusted events to the OneCompany durable GitHub ledger."""
from __future__ import annotations

import argparse
import json
import sys

from ledger_lib import derive, list_events, post_event
from onecompany_lib import CONTROL, github_repo_from_config, load_json
from platform_identity import authorize_current_principal

# These events have dedicated commands that bind the platform evidence needed to
# authorize them. The generic ledger publisher must never bypass those checks.
ROUTED_ONLY = {"GATE", "MERGED"}

# Administrative events may be appended generically only after authority is
# derived from the authenticated GitHub principal under an explicit trusted ref.
PRIVILEGED_AUTHORITIES = {
    "INTEGRITY_CONFLICT_RESOLVED": "root",
    "HUMAN_DECISION": "governance_change",
    "ROOT_TRUST_ROTATED": "root_rotation",
    "EMERGENCY_STOP_CLEARED": "emergency_control",
    "BUDGET_CHANGED": "budget_change",
    "GOVERNANCE_CHANGED": "governance_change",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    read = sub.add_parser("read")
    read.add_argument("--pr", type=int)
    read.add_argument("--events", action="store_true", help="Include trusted raw events")

    post = sub.add_parser("post")
    post.add_argument("--type", required=True)
    post.add_argument(
        "--actor",
        help="Logical actor label for non-privileged events; for privileged events this is assertion-only",
    )
    post.add_argument(
        "--trusted-ref",
        help="Exact reviewed base/ref defining identity authority for privileged events",
    )
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
        event_type = str(args.type)
        if event_type in ROUTED_ONLY:
            raise ValueError(
                f"{event_type} cannot be posted through generic ledger access; "
                "use the gate/merge command so platform evidence is verified"
            )

        authority = PRIVILEGED_AUTHORITIES.get(event_type)
        if authority:
            if not args.trusted_ref:
                raise ValueError(
                    f"privileged event {event_type} requires --trusted-ref for base-trusted identity authorization"
                )
            config = load_json(CONTROL / "config.json")
            repo = github_repo_from_config(config)
            if not repo:
                raise ValueError("config.project.repository must be owner/name")
            identity, errors = authorize_current_principal(
                repo, args.trusted_ref, authority
            )
            if identity is None:
                raise ValueError(
                    f"authenticated platform principal lacks {authority}: {','.join(errors)}"
                )
            actor = str(identity.get("actor_id"))
            login = str(identity.get("login"))
            if args.actor and args.actor not in {actor, login}:
                raise ValueError(
                    f"asserted actor {args.actor!r} does not match platform identity "
                    f"actor={actor!r} login={login!r}"
                )
            payload = {
                **payload,
                "platform_login": login,
                "identity_policy_provenance": identity.get("policy_provenance"),
            }
        else:
            if not args.actor:
                raise ValueError("non-privileged event requires --actor as a descriptive logical actor")
            actor = args.actor

        event = post_event(event_type, actor, payload)
        print(json.dumps(event, indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
