#!/usr/bin/env python3
"""Verify the bound disposable demo fixture before any request is served."""

from __future__ import annotations

import ipaddress
import sqlite3
from http.server import HTTPServer


def preflight(server: HTTPServer, store: object, plan: dict) -> dict[str, object]:
    """Inspect the ACTUAL bound socket, empty in-memory DB and planner result.

    Caller-declared booleans or hostnames cannot attest to safety. Fail closed
    before serve_forever begins; the owner brief and plan were already checked.
    """
    blockers: list[str] = []
    try:
        host = server.server_address[0]
        if not ipaddress.ip_address(host).is_loopback:
            blockers.append("non_local_bind")
    except (AttributeError, IndexError, TypeError, ValueError):
        blockers.append("unverified_bind")

    try:
        db = store.db
        if not isinstance(db, sqlite3.Connection):
            raise ValueError("store_not_sqlite")
        databases = db.execute("PRAGMA database_list").fetchall()
        if not databases or any(str(row[2]) != "" for row in databases):
            blockers.append("persistent_data_store")
        if store.list():
            blockers.append("nonempty_disposable_store")
    except (AttributeError, TypeError, ValueError, sqlite3.Error):
        blockers.append("unverified_disposable_store")

    if (not isinstance(plan, dict)
            or plan.get("authorization") != "NOT_GRANTED"
            or plan.get("mode") != "READ_ONLY_PROPOSAL"):
        blockers.append("execution_authority_not_permitted")
    return {
        "verified": not blockers,
        "blockers": blockers,
        "scope": "LOCAL_DISPOSABLE_DEMO_ONLY",
        "deployable": False,
        "approved": False,
    }


def require_safe_demo(server: HTTPServer, store: object, plan: dict) -> None:
    """Refuse an unverified fixture before starting its HTTP worker."""
    report = preflight(server, store, plan)
    if not report["verified"]:
        raise ValueError("DISPOSABLE_DEMO_SAFETY_BLOCKED:" +
                         ",".join(report["blockers"]))
