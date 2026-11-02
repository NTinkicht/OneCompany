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
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_REL = Path("examples") / "vertical-slice" / "app.py"
APP_PATH = ROOT / APP_REL
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


def _git(workspace: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(workspace), *args], capture_output=True, text=True, timeout=30)


def resolve_app(workspace: Path, head_sha: str, base_sha: str) -> Path:
    """Return the app source inside the bound workspace after proving it is the exact head."""
    app = Path(workspace) / APP_REL
    if not app.is_file():
        raise BindingError("workspace does not contain the application source")
    head = _git(workspace, "rev-parse", "HEAD")
    if head.returncode != 0 or head.stdout.strip() != head_sha:
        raise BindingError("workspace is not a git checkout at the supplied head_sha")
    if _git(workspace, "merge-base", "--is-ancestor", base_sha, head_sha).returncode != 0:
        raise BindingError("base_sha is not an ancestor of head_sha in the workspace")
    dirty = _git(workspace, "status", "--porcelain", "--untracked-files=no", "--", str(APP_REL.parent))
    if dirty.returncode != 0 or dirty.stdout.strip():
        raise BindingError("application source differs from the committed head")
    return app


def _load_app(app_path: Path):
    spec = importlib.util.spec_from_file_location("onecompany_runtime_binding_app", app_path)
    if not spec or not spec.loader:
        raise BindingError("cannot load application module")
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
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


def capture(wu_id: str, run_key: str, workspace: str | Path, head_sha: str, base_sha: str) -> dict:
    """Run the workspace's fixture on an ephemeral loopback port and return an evidence manifest."""
    workspace = Path(workspace)
    _check_ids(wu_id, run_key, workspace, head_sha, base_sha)
    app_path = resolve_app(workspace, head_sha, base_sha)
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
           head_sha: str, base_sha: str) -> list[str]:
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
    try:
        app_path = resolve_app(Path(workspace), head_sha, base_sha)
        if manifest["build_digest"] != build_digest(app_path):
            problems.append("build_digest mismatch")
    except (BindingError, OSError, subprocess.SubprocessError) as exc:
        problems.append(f"workspace unverifiable: {exc}")
    if manifest["production_qualified"] is not False or manifest["scope"] != SCOPE:
        problems.append("local demo must not be production-qualified")
    h, c, k = manifest["health"], manifest["crud_round_trip"], manifest["cleanup"]
    if not isinstance(h, dict) or h.get("status") != 200:
        problems.append("health evidence failed")
    if not (isinstance(c, dict) and c.get("create") in (200, 201) and c.get("update") == 200
            and c.get("list") == 200 and c.get("delete") in (200, 204) and c.get("ok") is True):
        problems.append("CRUD round trip failed")
    if not (isinstance(k, dict) and k.get("server_stopped") is True and k.get("port_closed") is True
            and k.get("ok") is True):
        problems.append("cleanup not verified")
    if str(manifest["started_at"]) > str(manifest["stopped_at"]):
        problems.append("stop precedes start")
    return problems


def project(manifest: object, *, ci_state: str | None, tests_passed: bool | None,
            current_head_sha: str, current_base_sha: str, wu_id: str, run_key: str,
            workspace: str | Path) -> dict:
    """Preview projection: only an exact, fully evidenced local run is ready_to_preview."""
    reasons = verify(manifest, wu_id=wu_id, run_key=run_key, workspace=workspace,
                     head_sha=current_head_sha, base_sha=current_base_sha)
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
