"""Precise local coordination-log append boundary.

Local filesystem failures that happen before the append is attempted remain
ordinary command failures. Once a write may have happened, callers receive an
explicit uncertainty error and must reconcile before retrying.
"""
from __future__ import annotations

import datetime as dt
import json
import uuid
from pathlib import Path
from typing import Any

import lease_lifecycle as lifecycle


class LocalEventMutationUncertainError(RuntimeError):
    """Raised only when a local coordination-log write may have mutated state."""


def _timestamp(value: dt.datetime | None = None) -> str:
    current = value or dt.datetime.now(dt.timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=dt.timezone.utc)
    return current.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def append_local_event(
    event_type: str,
    actor: str,
    payload: dict[str, Any],
    *,
    now: dt.datetime | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Append one local event while preserving the pre/post-mutation boundary."""
    target = path or lifecycle._local_event_path()

    # These operations occur before any append attempt. Their failures are safe
    # to report normally and must not be upgraded to mutation uncertainty.
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = lifecycle.local_events(target)

    event = {
        "version": 1,
        "event_id": str(uuid.uuid4()),
        "type": event_type,
        "actor": actor,
        "timestamp": _timestamp(now),
        "payload": payload,
        "local_sequence": len(existing) + 1,
    }
    serialized = json.dumps(
        event,
        separators=(",", ":"),
        ensure_ascii=False,
    ) + "\n"

    # Opening the file can fail before a write is attempted, so keep it outside
    # the uncertainty boundary. Once open succeeds, write/flush/close failures
    # are conservatively indeterminate because bytes may already be durable.
    handle = target.open("a", encoding="utf-8", newline="\n")
    try:
        with handle:
            written = handle.write(serialized)
            if written != len(serialized):
                raise LocalEventMutationUncertainError(
                    f"short local coordination write: {written}/{len(serialized)}"
                )
            handle.flush()
    except LocalEventMutationUncertainError:
        raise
    except OSError as exc:
        raise LocalEventMutationUncertainError(str(exc)) from exc
    return event
