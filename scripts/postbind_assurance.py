#!/usr/bin/env python3
"""Per-criterion post-binding assurance (OC-P0-15, WU-P1-POSTBIND-ASSURANCE-001).

Checks that EACH approved acceptance criterion of a WU has at least one evidence
item bound to the same WU, RunKey, exact head/base and build digest as the runtime
binding manifest from OC-P0-14 (`runtime_binding.verify` is reused, not copied).
Evidence artifacts are files whose sha256 is recomputed here; packet-authored
claims are never trusted. Offline: no network, no provider call. Fail closed:
anything missing, stale, mismatched or unknown is a named problem, and an
uncovered criterion is never treated as passing.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("runtime_binding", ROOT / "scripts" / "runtime_binding.py")
rb = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("runtime_binding", rb)
_spec.loader.exec_module(rb)

SCHEMA = "onecompany.postbind-assurance/v1"
KINDS = ("unit", "api", "browser", "security", "db")
CRIT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
BIND_KEYS = ("wu_id", "run_key", "head_sha", "base_sha", "build_digest")


class AssuranceError(ValueError):
    """Raised for malformed criteria/evidence input."""


def _artifact_digest(base: Path, rel: object) -> str | None:
    if not isinstance(rel, str) or not rel or Path(rel).is_absolute() or ".." in Path(rel).parts:
        return None
    root = base.resolve()
    cur = base
    for part in Path(rel).parts:  # inspect every unresolved component: resolve() would hide symlinks
        cur = cur / part
        if cur.is_symlink():
            return None
    p = cur.resolve()
    if root not in p.parents or not p.is_file():
        return None
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def criteria_digest(crits: list[dict]) -> str:
    """Canonical digest of the criterion set (ids + required kinds), independent of order."""
    canon = sorted((c["id"], sorted(c.get("required_kinds", []))) for c in crits)
    return "sha256:" + hashlib.sha256(json.dumps(canon, separators=(",", ":")).encode()).hexdigest()


def parse_criteria(doc: object, wu_id: str) -> list[dict]:
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA + "/criteria" or doc.get("wu_id") != wu_id:
        raise AssuranceError("criteria document missing, wrong schema or wrong wu_id")
    crits = doc.get("criteria")
    if not isinstance(crits, list) or not crits:
        raise AssuranceError("criteria list missing or empty")
    seen: set[str] = set()
    for c in crits:
        if not isinstance(c, dict) or not isinstance(c.get("id"), str) or not CRIT_RE.match(c["id"]):
            raise AssuranceError("criterion id missing or malformed")
        if c["id"] in seen:
            raise AssuranceError(f"duplicate criterion id: {c['id']}")
        seen.add(c["id"])
        req = c.get("required_kinds", [])
        if not isinstance(req, list) or any(k not in KINDS for k in req):
            raise AssuranceError(f"criterion {c['id']}: required_kinds must be a list of {KINDS}")
    return crits


def assess(criteria_doc: object, evidence_doc: object, manifest: object, *, wu_id: str, run_key: str,
           workspace: str | Path, head_sha: str, base_sha: str, evidence_dir: str | Path,
           approved_criteria_sha256: str) -> dict:
    """Return {covered, uncovered, problems, ok}. ok only when every criterion is covered and no problem exists."""
    crits = parse_criteria(criteria_doc, wu_id)
    # The criterion set is pinned to the digest recorded at approval, so a caller cannot
    # drop or edit criteria (from both criteria and evidence) and still reach ok.
    if not isinstance(approved_criteria_sha256, str) or approved_criteria_sha256 != criteria_digest(crits):
        raise AssuranceError("criteria do not match the approved criteria digest")
    problems = [f"runtime binding: {p}" for p in rb.verify(
        manifest, wu_id=wu_id, run_key=run_key, workspace=workspace, head_sha=head_sha, base_sha=base_sha)]
    expected = {"wu_id": wu_id, "run_key": run_key, "head_sha": head_sha, "base_sha": base_sha}
    if isinstance(manifest, dict):
        expected["build_digest"] = manifest.get("build_digest")
    items = evidence_doc.get("items") if isinstance(evidence_doc, dict) else None
    if not isinstance(evidence_doc, dict) or evidence_doc.get("schema") != SCHEMA + "/evidence" or not isinstance(items, list):
        return {"covered": [], "uncovered": [c["id"] for c in crits], "ok": False,
                "problems": problems + ["evidence document missing or malformed"]}
    ids = {c["id"] for c in crits}
    base = Path(evidence_dir)
    good: dict[str, set[str]] = {i: set() for i in ids}
    for n, it in enumerate(items):
        tag = f"evidence[{n}]"
        if not isinstance(it, dict):
            problems.append(f"{tag}: not an object"); continue
        cid = it.get("criterion_id")
        if cid not in ids:
            problems.append(f"{tag}: unknown criterion {cid!r}"); continue
        tag = f"{tag} ({cid})"
        if it.get("kind") not in KINDS:
            problems.append(f"{tag}: unknown kind"); continue
        bad = [k for k in BIND_KEYS if not expected.get(k) or it.get(k) != expected[k]]
        if bad:
            problems.append(f"{tag}: stale or mismatched binding ({', '.join(bad)})"); continue
        if it.get("result") != "pass":
            problems.append(f"{tag}: result is not pass"); continue
        claimed = it.get("artifact_sha256")
        actual = _artifact_digest(base, it.get("artifact"))
        if not isinstance(claimed, str) or not SHA256_RE.match(claimed) or actual is None or actual != claimed:
            problems.append(f"{tag}: artifact missing, unsafe or digest mismatch"); continue
        good[cid].add(it["kind"])
    covered, uncovered = [], []
    for c in crits:
        have, need = good[c["id"]], set(c.get("required_kinds", []))
        ok = bool(have) and need <= have
        (covered if ok else uncovered).append(c["id"])
        if not ok:
            missing = sorted(need - have) if have else ["any"]
            problems.append(f"criterion {c['id']} uncovered (missing kinds: {', '.join(missing)})")
    return {"covered": covered, "uncovered": uncovered, "problems": problems,
            "ok": not uncovered and not problems}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Per-criterion post-binding assurance (offline, fail closed)")
    p.add_argument("--wu", required=True); p.add_argument("--run-key", required=True)
    p.add_argument("--workspace", default="."); p.add_argument("--head", required=True)
    p.add_argument("--base", required=True); p.add_argument("--criteria", required=True)
    p.add_argument("--evidence", required=True); p.add_argument("--manifest", required=True)
    p.add_argument("--evidence-dir", required=True)
    p.add_argument("--approved-criteria-sha256", required=True,
                   help="criteria digest recorded at approval (see criteria_digest)")
    a = p.parse_args(argv)
    try:
        docs = [json.loads(Path(f).read_text(encoding="utf-8")) for f in (a.criteria, a.evidence, a.manifest)]
        mf = docs[2].get("manifest", docs[2]) if isinstance(docs[2], dict) else docs[2]
        report = assess(docs[0], docs[1], mf, wu_id=a.wu, run_key=a.run_key, workspace=a.workspace,
                        head_sha=a.head, base_sha=a.base, evidence_dir=a.evidence_dir,
                        approved_criteria_sha256=a.approved_criteria_sha256)
    except (AssuranceError, OSError, ValueError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
