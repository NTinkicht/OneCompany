#!/usr/bin/env python3
"""Source-only Mistral coding/test worker with trusted parent-controlled GitHub publication.

Model sees ONLY a bounded isolated source stage and NEVER the publisher token.
Every branch write requires a live OneCompany lease from the durable ledger,
protected-main WU exact path scope, current PR head/base and USD0 policy.
This is not an alternative lease issuer, reviewer or merge agent.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import lease_lifecycle
from onecompany_lib import CONTROL, emergency_stop_active, load_json
from mistral_cloud_review import REPO, SHA, current_pr

WAKE_ISSUE = 130
MARKER = "MISTRAL_WORK_V1"
OWNER = "NTinkicht"
STAGE = Path("/tmp/onecompany-mistral-code-stage")
TRUSTED = Path("/tmp/onecompany-mistral-code-trusted")
ALLOWED_PREFIXES = ("examples/", "src/", "app/", "tests/")
SAFE_PATH = re.compile(r"(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\Z")
MAX_FILE = 24_000
MAX_TOTAL = 72_000
MAX_FILES = 8
FIELDS = ("pr", "head_sha", "base_sha", "work_unit", "lease_id")


def actions_output(**fields: object) -> None:
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
        for key, value in fields.items():
            if "\r" in str(value) or "\n" in str(value):
                raise ValueError("ACTIONS_OUTPUT_INJECTION")
            stream.write(f"{key}={value}\n")


def assignment(body: str) -> dict:
    if (not isinstance(body, str) or len(body) > 3000
        or body.count(MARKER) != 1 or f"\n{MARKER}\n" not in body
        or not body.startswith("@mistral-vibe\n")):
        raise ValueError("WORK_ASSIGNMENT_INVALID")
    lines = body.splitlines()
    if len(lines) != 7 or lines[:2] != ["@mistral-vibe", MARKER]:
        raise ValueError("WORK_ASSIGNMENT_FIELDS_INVALID")
    values: dict[str, str] = {}
    for line, name in zip(lines[2:], FIELDS):
        if not line.startswith(name + ": "):
            raise ValueError("WORK_ASSIGNMENT_FIELD_INVALID")
        values[name] = line[len(name) + 2:]
    if (not re.fullmatch(r"[1-9]\d{0,5}", values["pr"])
        or not SHA.fullmatch(values["head_sha"])
        or not SHA.fullmatch(values["base_sha"])
        or values["head_sha"] == values["base_sha"]
        or not re.fullmatch(r"WU-[A-Z0-9-]{3,64}", values["work_unit"])
        or not re.fullmatch(r"[A-Za-z0-9_-]{12,80}", values["lease_id"])):
        raise ValueError("WORK_ASSIGNMENT_VALUES_INVALID")
    return {**values, "pr": int(values["pr"])}


def zero_spend() -> None:
    ai = load_json(CONTROL / "budget.json")["ai"]
    if (type(ai.get("additional_monthly_spend_cap")) is not int
        or ai["additional_monthly_spend_cap"] != 0
        or any(ai.get(name) is not False for name in (
            "allow_paid_fallback", "allow_overage", "allow_auto_topup",
            "allow_new_paid_vendor",
        ))):
        raise ValueError("BUDGET_BLOCKED")
    if emergency_stop_active():
        raise ValueError("EMERGENCY_STOP")


def literal_paths(values: object) -> tuple[str, ...]:
    """Single PR changes exactly the protected WU's literal model-write scope."""
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_FILES:
        raise ValueError("SCOPE_SIZE_BLOCKED")
    seen: set[str] = set()
    for path in values:
        if (not isinstance(path, str) or not SAFE_PATH.fullmatch(path)
            or not path.startswith(ALLOWED_PREFIXES)
            or any(part in (".", "..", ".git", ".vibe", "__pycache__")
                   for part in Path(path).parts)
            or any(part.startswith(".env") for part in Path(path).parts)
            or path.endswith((".key", ".pem", ".p12", ".pfx"))
            or path in seen):
            raise ValueError("MODEL_WRITE_SCOPE_INVALID")
        seen.add(path)
    return tuple(values)


def live_ticket(value: dict) -> dict:
    """Must execute on trusted protected-main checkout with GH_TOKEN read."""
    if os.environ.get("GITHUB_REPOSITORY") != REPO:
        raise ValueError("FOREIGN_REPOSITORY")
    zero_spend()
    pr = current_pr(value["pr"], value["head_sha"], value["base_sha"])
    branch = (pr.get("head") or {}).get("ref")
    if not isinstance(branch, str) or branch == "main" or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}", branch
    ):
        raise ValueError("UNSAFE_WORK_BRANCH")
    queue = load_json(CONTROL / "queue.json")
    matches = [item for item in queue.get("work_units", [])
               if item.get("id") == value["work_unit"]]
    if len(matches) != 1 or matches[0].get("status") != "READY":
        raise ValueError("WORK_UNIT_NOT_READY")
    item = matches[0]
    if item.get("pr") != value["pr"] or item.get("branch") != branch:
        raise ValueError("WORK_UNIT_PR_MISMATCH")
    scope = literal_paths(item.get("write_scope"))
    if item.get("risk_class") not in ("LOW", "MEDIUM"):
        raise ValueError("MODEL_HIGH_RISK_BLOCKED")
    view = lease_lifecycle.coordination_view(pr=value["pr"])
    if view.get("integrity_conflicts") or view.get("conflicts"):
        raise ValueError("LEDGER_INTEGRITY_BLOCKED")
    active = [lease for lease in view.get("active_leases", [])
              if lease.get("role") == "implementation"]
    if len(active) != 1:
        raise ValueError("UNIQUE_LEASE_REQUIRED")
    lease = active[0]
    if (lease.get("id") != value["lease_id"]
        or lease.get("actor") != "mistral-vibe"
        or lease.get("work_unit") != value["work_unit"]
        or lease.get("pr") != value["pr"]
        or lease.get("branch") != branch
        or lease.get("status") != "active"
        or (lease.get("last_progress_head") or lease.get("start_head"))
           != value["head_sha"]
        or tuple(lease.get("planning_snapshot", {}).get("write_scope", [])) != scope):
        raise ValueError("STALE_OR_FOREIGN_MODEL_LEASE")
    # No candidate version of policy or a public issue may add scope.
    return {**value, "branch": branch, "scope": list(scope),
            "title": str(item.get("title", ""))[:160]}


def tracked_mode(head: str, path: str) -> str | None:
    """Refuse staged Git symlinks, executable blobs and file-valued ancestors.

    Model-authorized files may be new regular files or existing regular blobs;
    a model cannot silently turn a Git symlink/tree/executable into a file.
    The tree is pinned to the PR's exact head, not the workspace checkout.
    """
    parts = path.split("/")
    mode = None
    for depth in range(1, len(parts) + 1):
        prefix = "/".join(parts[:depth])
        response = subprocess.run(
            ["git", "ls-tree", "-z", head, "--", prefix],
            capture_output=True, timeout=15, check=False,
            env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
        )
        if response.returncode != 0:
            raise ValueError("GIT_TREE_INSPECTION_FAILED")
        rows = [row for row in response.stdout.split(b"\\0") if row]
        if not rows:
            mode = None
            continue
        if len(rows) != 1 or b"\\t" not in rows[0]:
            raise ValueError("GIT_TREE_ENTRY_INVALID")
        header, raw_name = rows[0].split(b"\\t", 1)
        fields = header.split(b" ")
        if len(fields) != 3 or raw_name != prefix.encode("utf-8"):
            raise ValueError("GIT_TREE_ENTRY_INVALID")
        mode = fields[0].decode("ascii")
        if depth < len(parts) and mode != "040000":
            raise ValueError("MODEL_SCOPE_NON_DIRECTORY_ANCESTOR")
        if depth == len(parts) and mode != "100644":
            raise ValueError("MODEL_SCOPE_NOT_REGULAR_BLOB")
    return mode


def git_file(head: str, path: str) -> bytes | None:
    mode = tracked_mode(head, path)
    response = subprocess.run(
        ["git", "show", f"{head}:{path}"], text=False, capture_output=True,
        timeout=15, check=False,
        env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    )
    if response.returncode == 0 and mode is None:
        raise ValueError("GIT_TREE_SOURCE_INCONSISTENT")
    if response.returncode != 0 and mode is not None:
        raise ValueError("GIT_TRACKED_SOURCE_UNREADABLE")
    if response.returncode != 0:
        # Missing paths are allowed as explicit WU-scoped NEW files. Fail
        # instead of treating all repo/API errors as a missing file.
        check = subprocess.run(
            ["git", "cat-file", "-e", head],
            capture_output=True, timeout=15, check=False,
        )
        if check.returncode != 0:
            raise ValueError("PR_COMMIT_OBJECT_UNAVAILABLE")
        return None
    if len(response.stdout) > MAX_FILE:
        raise ValueError("SCOPE_SOURCE_FILE_TOO_LARGE")
    return response.stdout


def stage_files(ticket: dict, *, stage: Path = STAGE,
                manifest: Path = TRUSTED / "manifest.json") -> dict:
    """Only immutable WU path list is exposed; no Git credential or PR checkout."""
    stage.mkdir(parents=True, mode=0o700, exist_ok=False)
    manifest.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    total = 0
    records = []
    for path in ticket["scope"]:
        content = git_file(ticket["head_sha"], path)
        if content is not None:
            content.decode("utf-8")
        data = content if content is not None else b""
        total += len(data)
        if total > MAX_TOTAL:
            raise ValueError("STAGE_SOURCE_TOO_LARGE")
        destination = stage / "source" / path
        destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        destination.write_bytes(data)
        records.append({
            "path": path, "sha256": hashlib.sha256(data).hexdigest(),
            "existed": content is not None,
        })
    (stage / "task.txt").write_text(
        f"Work unit: {ticket['work_unit']}\nTitle: {ticket['title']}\n"
        f"PR: {ticket['pr']}\nHead: {ticket['head_sha']}\n"
        "This is an isolated coding + deterministic unit-test contribution. "
        "Read source/ files and edit ONLY scoped source/ paths. "
        "No runtime shell, Git, network, secrets, merge or approval.\n",
        encoding="utf-8",
    )
    manifest.write_text(json.dumps({"ticket": ticket, "files": records,
                                    "task_sha256": hashlib.sha256(
                                        (stage / "task.txt").read_bytes()
                                    ).hexdigest()}))
    return {"ticket": ticket, "files": records}


def planned_edits(*, stage: Path = STAGE,
                  manifest: Path = TRUSTED / "manifest.json") -> list[dict]:
    """Read only exact declared files; reject symlink, unlisted and empty edits."""
    trusted = json.loads(manifest.read_text(encoding="utf-8"))
    allowed = {row["path"]: row for row in trusted["files"]}
    if (hashlib.sha256((stage / "task.txt").read_bytes()).hexdigest()
        != trusted["task_sha256"]):
        raise ValueError("MODEL_CHANGED_WORK_ORDER")
    actual: set[str] = set()
    for path in stage.rglob("*"):
        if path.is_symlink():
            raise ValueError("MODEL_STAGE_SYMLINK_BLOCKED")
        if path.is_file():
            rel = path.relative_to(stage).as_posix()
            if rel != "task.txt":
                if not rel.startswith("source/") or rel[7:] not in allowed:
                    raise ValueError("MODEL_OUT_OF_SCOPE_WRITE")
                actual.add(rel[7:])
    if actual != set(allowed):
        raise ValueError("MODEL_STAGE_MISSING_FILE")
    rows = []
    total = 0
    for name, record in allowed.items():
        data = (stage / "source" / name).read_bytes()
        data.decode("utf-8")
        total += len(data)
        if len(data) > MAX_FILE or total > MAX_TOTAL:
            raise ValueError("MODEL_OUTPUT_TOO_LARGE")
        if hashlib.sha256(data).hexdigest() != record["sha256"]:
            rows.append({"path": name, "content": data,
                         "existed": record["existed"]})
    if not rows:
        raise ValueError("MODEL_PRODUCED_NO_CODE_OR_TEST")
    return rows


def api(route: str, *, method: str = "GET", payload: dict | None = None):
    args = ["gh", "api"]
    if method != "GET":
        args += ["-X", method]
    args.append(route)
    if payload is not None:
        args += ["--input", "-"]
    result = subprocess.run(args, input=json.dumps(payload) if payload is not None else None,
                            capture_output=True, text=True, check=False, timeout=30)
    if result.returncode != 0:
        raise ValueError("GITHUB_PUBLISH_FAILED")
    return json.loads(result.stdout)


def publish(ticket: dict, *, stage: Path = STAGE,
            manifest: Path = TRUSTED / "manifest.json") -> str:
    """Atomically construct exact-parent commit and fast-forward PR branch only."""
    # Immediately refresh durable lease and PR before any mutation.
    current = live_ticket(ticket)
    if current["scope"] != ticket["scope"] or current["branch"] != ticket["branch"]:
        raise ValueError("STALE_MODEL_SCOPE")
    edits = planned_edits(stage=stage, manifest=manifest)
    head = current["head_sha"]
    parent = api(f"repos/{REPO}/git/commits/{head}")
    if (not isinstance(parent.get("tree"), dict)
        or not SHA.fullmatch(parent["tree"].get("sha") or "")):
        raise ValueError("GIT_PARENT_TREE_MISSING")
    updates = []
    for row in edits:
        blob = api(f"repos/{REPO}/git/blobs", method="POST", payload={
            "content": base64.b64encode(row["content"]).decode("ascii"),
            "encoding": "base64",
        })
        if not SHA.fullmatch(blob.get("sha") or ""):
            raise ValueError("GIT_BLOB_UNVERIFIED")
        updates.append({"path": row["path"], "mode": "100644",
                        "type": "blob", "sha": blob["sha"]})
    tree = api(f"repos/{REPO}/git/trees", method="POST", payload={
        "base_tree": parent["tree"]["sha"], "tree": updates,
    })
    if not SHA.fullmatch(tree.get("sha") or ""):
        raise ValueError("GIT_TREE_UNVERIFIED")
    new = api(f"repos/{REPO}/git/commits", method="POST", payload={
        "message": (
            f"feat({ticket['work_unit']}): bounded Mistral code and tests\n\n"
            "Material-Author: mistral-vibe\n"
            f"Work-Unit: {ticket['work_unit']}\n"
            f"Lease-ID: {ticket['lease_id']}\n"
            f"Expected-Parent: {head}"
        ),
        "tree": tree["sha"], "parents": [head],
    })
    new_sha = new.get("sha")
    if not isinstance(new_sha, str) or not SHA.fullmatch(new_sha):
        raise ValueError("GIT_COMMIT_UNVERIFIED")
    # One last exact-head/lease check; never force a stale branch.
    live_ticket(ticket)
    api(f"repos/{REPO}/git/refs/heads/{ticket['branch']}",
        method="PATCH", payload={"sha": new_sha, "force": False})
    return new_sha


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        if mode == "prepare":
            if os.environ.get("GITHUB_ACTOR") != OWNER:
                raise ValueError("UNTRUSTED_DISPATCH_AUTHOR")
            ticket = live_ticket(assignment(os.environ["DISPATCH_BODY"]))
            (TRUSTED).mkdir(parents=True, mode=0o700, exist_ok=True)
            (TRUSTED / "ticket.json").write_text(json.dumps(ticket))
            actions_output(ready="true", status="WORK_TICKET_VERIFIED")
        elif mode == "stage":
            ticket = json.loads((TRUSTED / "ticket.json").read_text())
            live_ticket(ticket)
            stage_files(ticket)
            actions_output(ready="true", status="MODEL_STAGE_READY")
        elif mode == "publish":
            ticket = json.loads((TRUSTED / "ticket.json").read_text())
            new_sha = publish(ticket)
            actions_output(ready="true", status="MISTRAL_CODE_COMMITTED_AWAIT_CI",
                           new_sha=new_sha, pr=ticket["pr"])
        else:
            raise ValueError("UNKNOWN_WORKER_MODE")
    except (ValueError, OSError, UnicodeError, json.JSONDecodeError, KeyError,
            subprocess.CalledProcessError, subprocess.TimeoutExpired):
        actions_output(ready="false", status="MISTRAL_WORK_BLOCKED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
