#!/usr/bin/env python3
"""Prove an honest Phase-1 draft-to-real-local-app slice without granting authority."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from brief_handoff_proposal import propose
from first_run_journey import read_brief, view
from onboard import analyze
from planner import consume_brief_handoff
import local_preview_evidence
from demo_safety import require_safe_demo

ROOT = Path(__file__).resolve().parents[1]


def _local_app():
    """Load the existing disposable app fixture, never a new server implementation."""
    module_path = ROOT / "examples" / "vertical-slice" / "app.py"
    spec = importlib.util.spec_from_file_location("onecompany_vertical_fixture", module_path)
    if spec is None or spec.loader is None:
        raise ValueError("LOCAL_APP_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _request(root: str, method: str, path: str,
             payload: dict | None = None, origin: str | None = None) -> tuple[int, dict]:
    """Call only the fixture's ephemeral loopback origin with bounded JSON."""
    headers = {"X-OneCompany-Local": "1", "Content-Type": "application/json"}
    if origin is not None:
        headers["Origin"] = origin
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(root + path.lstrip("/"), method=method,
                                     data=data, headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        response = opener.open(request, timeout=2)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        return response.status, json.loads(response.read(4096).decode("utf-8"))


def _assert_response(actual: tuple[int, dict], status: int) -> dict:
    """Reject any unexpected HTTP status without claiming the local app passed."""
    if actual[0] != status:
        raise ValueError(f"LOCAL_CRUD_FAILED_expected_{status}_got_{actual[0]}")
    return actual[1]


def run(assessment: dict, saved_brief: dict, head: str, base: str) -> dict:
    """Validate draft→existing planner, then exercise real ephemeral HTTP CRUD."""
    guidance = view(assessment, saved_brief)
    if guidance["stage"] != "PROPOSAL_READY_NOT_APPROVED":
        raise ValueError("COMPLETE_OWNER_BRIEF_REQUIRED")
    proposal = propose(saved_brief, head, base)
    plan = consume_brief_handoff(proposal, head, base)
    if plan["authorization"] != "NOT_GRANTED" or plan["mode"] != "READ_ONLY_PROPOSAL":
        raise ValueError("READ_ONLY_PLANNING_REQUIRED")

    app = _local_app()
    server, store = app.start_server(0)
    worker = None
    try:
        # Verify the actual socket/store/plan BEFORE accepting HTTP requests.
        require_safe_demo(server, store, plan)
        worker = threading.Thread(target=server.serve_forever,
                                  kwargs={"poll_interval": 0.05}, daemon=True)
        worker.start()
        root = f"http://127.0.0.1:{server.server_port}/"
        for _ in range(30):
            try:
                health = local_preview_evidence.collect(head, root, timeout=0.5)
                break
            except ValueError:
                time.sleep(0.05)
        else:
            raise ValueError("LOCAL_FIXTURE_HEALTH_FAILED")
        if health.get("revision") != head or health.get("health") != "PASS":
            raise ValueError("LOCAL_FIXTURE_HEALTH_FAILED")

        title = "OneCompany local smoke"
        created = _assert_response(_request(root, "POST", "api/items",
                                            {"title": title}), 201)
        item_id = created["id"]
        if created["title"] != title or created["done"] is not False:
            raise ValueError("LOCAL_CRUD_CREATE_FAILED")
        listed = _assert_response(_request(root, "GET", "api/items"), 200)
        if not any(item["id"] == item_id for item in listed["items"]):
            raise ValueError("LOCAL_CRUD_LIST_FAILED")
        _assert_response(_request(root, "PATCH", f"api/items/{item_id}",
                                  {"done": True}), 200)
        listed = _assert_response(_request(root, "GET", "api/items"), 200)
        if not any(item["id"] == item_id and item["done"] is True
                   for item in listed["items"]):
            raise ValueError("LOCAL_CRUD_COMPLETE_FAILED")
        _assert_response(_request(root, "DELETE", f"api/items/{item_id}"), 200)
        if any(item["id"] == item_id for item in
               _assert_response(_request(root, "GET", "api/items"), 200)["items"]):
            raise ValueError("LOCAL_CRUD_DELETE_FAILED")
        _assert_response(_request(root, "DELETE", f"api/items/{item_id}"), 404)
        _assert_response(_request(root, "POST", "api/items", {"title": "blocked"},
                                  origin="https://remote.example"), 403)
    finally:
        # BaseServer.shutdown() deadlocks if serve_forever never started.
        if worker is not None:
            server.shutdown()
        server.server_close()
        if worker is not None:
            worker.join(timeout=2)
        store.close()

    return {
        "schema": "onecompany.phase1-vertical-smoke.v1",
        "status": "LOCAL_FIXTURE_PROVEN_ONLY",
        "path": guidance["path"],
        "project": guidance["project"],
        "owner_brief": "VALID_DRAFT_NOT_APPROVED",
        "planning": {
            "schema": plan["schema"],
            "mode": "READ_ONLY_PROPOSAL",
            "authorization": "NOT_GRANTED",
        },
        "source_refs_unverified": {"head": head, "base": base},
        "real_local_http": {
            "status": "PASS",
            "health": "PASS",
            "flow": "create_list_complete_delete_and_negative_refusals",
            "fixture_discarded": True,
        },
        "browser_qualification_in_this_run": False,
        "exact_head_ci_verified_in_this_run": False,
        "independent_review_in_this_run": False,
        "owner_implementation_approved": False,
        "canonical_work_unit": None,
        "run_key": None,
        "lease_id": None,
        "deployable": False,
        "requested_extra_spend": 0,
        "next_action": "Trusted parent must verify real head/base, owner approval, "
                       "canonical WU/lease and independent exact-head CI/review; "
                       "this disposable demonstration grants no authority.",
    }


def main(argv: list[str] | None = None) -> int:
    """Run against explicit owner draft and disposable Create/Adopt target."""
    parser = argparse.ArgumentParser(description="Phase-1 honest local vertical smoke")
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--brief", type=Path, required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--base", required=True)
    args = parser.parse_args(argv)
    try:
        assessment = analyze(args.target.resolve(), repository=args.repository)
        if assessment["blockers"] or assessment["journey"]["path"] not in ("create", "adopt"):
            raise ValueError("SAFE_CREATE_OR_ADOPT_TARGET_REQUIRED")
        result = run(assessment, read_brief(args.brief), args.head, args.base)
    except (ValueError, TypeError, OSError, KeyError,
            urllib.error.URLError) as exc:
        print("BLOCKED: " + str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
