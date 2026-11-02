#!/usr/bin/env python3
"""Bind the disposable vertical-slice runtime to WU + RunKey + workspace + exact PR head/base.

First slice of OC-P0-14 (WU-P1-RUNTIME-BINDING-001). Loopback only: starts the
local fixture on an ephemeral 127.0.0.1 port, captures health and CRUD
round-trip evidence, stops it, verifies cleanup, and writes an evidence
manifest. A local demo is never production-qualified.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import importlib.util
import json
import re
import socket
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "examples" / "vertical-slice" / "app.py"
SCHEMA = "onecompany.runtime-binding/v1"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
WU_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:#-]{0,127}$")
RUN_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
REQUIRED = (
    "schema", "wu_id", "run_key", "workspace", "head_sha", "base_sha", "build_digest",
    "started_at", "stopped_at", "health", "crud_round_trip", "cleanup",
    "production_qualified", "scope",
)
SCOPE = "local-demo-loopback-only"


class BindingError(ValueError):
    """Raised when binding input or evidence is missing, mismatched or unsafe."""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def build_digest(app_path: Path = APP_PATH) -> str:
    return "sha256:" + hashlib.sha256(app_path.read_bytes()).hexdigest()


def _load_app(app_path: Path):
    spec = importlib.util.spec_from_file_location("onecompany_runtime_binding_app", app_path)
    if not spec or not spec.loader:
        raise BindingError("cannot load application module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _check_ids(wu_id: str, run_key: str, workspace: Path, head: str, base: str) -> None:
    if not isinstance(wu_id, str) or not WU_RE.match(wu_id):
        raise BindingError("wu_id missing or malformed")
    if not isinstance(run_key, str) or not RUN_KEY_RE.match(run_key):
        raise BindingError("run_key missing or malformed")
    for label, sha in (("head_sha", head), ("base_sha", base)):
        if not isinstance(sha, str) or not SHA_RE.match(sha):
            raise BindingError(f"{label} must be a full 40-hex commit SHA")
    if not Path(workspace).is_dir():
        raise BindingError("workspace is not an existing directory")


def _request(port: int, method: str, path: str, body: dict | None = None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        headers = {"Host": f"127.0.0.1:{port}"}
        payload = None
        if body is not None:
            payload = json.dumps(body)
            headers.update({"Content-Type": "application/json", "X-OneCompany-Local": "1"})
        elif method != "GET":
            headers["X-OneCompany-Local"] = "1"
        conn.request(method, path, body=payload, headers=headers)
        resp = conn.getresponse()
        raw = resp.read()
        return resp.status, (json.loads(raw) if raw else None)
    finally:
        conn.close()


def capture(wu_id: str, run_key: str, workspace: str | Path, head_sha: str, base_sha: str,
            app_path: Path = APP_PATH) -> dict:
    """Run the fixture on an ephemeral loopback port and return an evidence manifest."""
    workspace = Path(workspace)
    _check_ids(wu_id, run_key, workspace, head_sha, base_sha)
    app = _load_app(app_path)
    digest = build_digest(app_path)
    started = _now()
    server, store = app.start_server(0)
    host, port = server.server_address[0], server.server_port
    if host != "127.0.0.1":
        server.server_close(); store.close()
        raise BindingError("runtime bound to a non-loopback address")
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    health = {"status": None}
    crud = {"ok": False}
    try:
        status, _ = _request(port, "GET", "/health")
        health = {"status": status}
        s1, created = _request(port, "POST", "/api/items", {"title": "binding-evidence"})
        item_id = (created or {}).get("id") if isinstance(created, dict) else None
        s2, _ = _request(port, "PATCH", f"/api/items/{item_id}", {"done": True}) if item_id else (None, None)
        s3, listed = _request(port, "GET", "/api/items")
        s4, _ = _request(port, "DELETE", f"/api/items/{item_id}") if item_id else (None, None)
        items = listed.get("items", listed) if isinstance(listed, dict) else listed
        seen = isinstance(items, list) and any(i.get("id") == item_id and i.get("done") is True for i in items)
        crud = {"create": s1, "update": s2, "list": s3, "delete": s4,
                "ok": s1 in (200, 201) and s2 == 200 and s3 == 200 and s4 in (200, 204) and bool(seen)}
    finally:
        server.shutdown()
        server.server_close()
        store.close()
        thread.join(timeout=5)
    stopped = _now()
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            port_closed = False
    except OSError:
        port_closed = True
    cleanup = {"server_stopped": not thread.is_alive(), "port_closed": port_closed}
    cleanup["ok"] = all(cleanup.values())
    return {
        "schema": SCHEMA, "wu_id": wu_id, "run_key": run_key, "workspace": str(workspace.resolve()),
        "head_sha": head_sha, "base_sha": base_sha, "build_digest": digest,
        "started_at": started, "stopped_at": stopped, "port": port,
        "health": health, "crud_round_trip": crud, "cleanup": cleanup,
        "production_qualified": False, "scope": SCOPE,
    }


def verify(manifest: object, *, wu_id: str, run_key: str, workspace: str | Path,
           head_sha: str, base_sha: str, app_path: Path = APP_PATH) -> list[str]:
    """Return a list of refusal reasons; empty means the manifest binds to the expectation."""
    if not isinstance(manifest, dict):
        return ["manifest is not an object"]
    problems = [f"missing field: {k}" for k in REQUIRED if manifest.get(k) in (None, "")]
    if problems:
        return problems
    if manifest["schema"] != SCHEMA:
        problems.append("unknown schema")
    expected = {"wu_id": wu_id, "run_key": run_key, "head_sha": head_sha, "base_sha": base_sha,
                "workspace": str(Path(workspace).resolve())}
    problems += [f"{k} mismatch" for k, v in expected.items() if manifest[k] != v]
    if manifest["build_digest"] != build_digest(app_path):
        problems.append("build_digest mismatch")
    if manifest["production_qualified"] is not False or manifest["scope"] != SCOPE:
        problems.append("local demo must not be production-qualified")
    if not isinstance(manifest["health"], dict) or manifest["health"].get("status") != 200:
        problems.append("health evidence failed")
    if not isinstance(manifest["crud_round_trip"], dict) or manifest["crud_round_trip"].get("ok") is not True:
        problems.append("CRUD round trip failed")
    if not isinstance(manifest["cleanup"], dict) or manifest["cleanup"].get("ok") is not True:
        problems.append("cleanup not verified")
    if str(manifest["started_at"]) > str(manifest["stopped_at"]):
        problems.append("stop precedes start")
    return problems


def project(manifest: object, *, ci_state: str | None, tests_passed: bool | None,
            current_head_sha: str, current_base_sha: str, wu_id: str, run_key: str,
            workspace: str | Path, app_path: Path = APP_PATH) -> dict:
    """Preview projection: only an exact, fully evidenced local run is ready_to_preview."""
    reasons = verify(manifest, wu_id=wu_id, run_key=run_key, workspace=workspace,
                     head_sha=current_head_sha, base_sha=current_base_sha, app_path=app_path)
    if ci_state != "success":
        reasons.append("CI evidence absent or not successful")
    if tests_passed is not True:
        reasons.append("tests not passed")
    return {"state": "blocked" if reasons else "ready_to_preview", "reasons": reasons,
            "label": "local demo, not production-qualified", "production_qualified": False}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Bind the local runtime to WU/RunKey/head/base (loopback only)")
    p.add_argument("--wu", required=True)
    p.add_argument("--run-key", required=True)
    p.add_argument("--workspace", default=".")
    p.add_argument("--head", required=True)
    p.add_argument("--base", required=True)
    p.add_argument("--ci", default=None, help="CI conclusion for the head, e.g. success")
    p.add_argument("--tests", choices=["passed", "failed"], default=None)
    p.add_argument("--out", default=None)
    a = p.parse_args(argv)
    try:
        manifest = capture(a.wu, a.run_key, a.workspace, a.head, a.base)
    except BindingError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    projection = project(manifest, ci_state=a.ci, tests_passed=None if a.tests is None else a.tests == "passed",
                         current_head_sha=a.head, current_base_sha=a.base, wu_id=a.wu,
                         run_key=a.run_key, workspace=a.workspace)
    out = {"manifest": manifest, "projection": projection}
    text = json.dumps(out, indent=2, sort_keys=True)
    if a.out:
        Path(a.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if projection["state"] == "ready_to_preview" else 1


if __name__ == "__main__":
    raise SystemExit(main())
