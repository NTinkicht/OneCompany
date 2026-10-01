#!/usr/bin/env python3
"""Canonical durable-ledger contract for Claude L5 controllers.

Storage rule: the ledger lives at `.l5/controller-ledger.json` on the dedicated
`l5/controller-ledger` branch. A writer MUST read the current file blob SHA and
use that exact SHA as the GitHub Contents API update precondition. The functions
here additionally enforce monotonic document/record versions. They perform no
network I/O and hold no credentials.
"""
from __future__ import annotations
import copy,json
from typing import Any,Mapping
from l5_kernel import HUMAN_CLEAR_ONLY,RepoMode

SCHEMA_VERSION=1
LEDGER_PATH=".l5/controller-ledger.json"
LEDGER_BRANCH="l5/controller-ledger"

class LedgerConflict(RuntimeError):pass
class LedgerInvalid(ValueError):pass

def validate_ledger(doc:Mapping[str,Any],*,expected_repo:str|None=None)->None:
    if not isinstance(doc,Mapping):raise LedgerInvalid("LEDGER_NOT_OBJECT")
    if doc.get("schema_version")!=SCHEMA_VERSION:raise LedgerInvalid("LEDGER_SCHEMA")
    repo=doc.get("repository")
    if not isinstance(repo,str) or not repo:raise LedgerInvalid("LEDGER_REPOSITORY")
    if expected_repo is not None and repo!=expected_repo:raise LedgerInvalid("LEDGER_REPOSITORY_MISMATCH")
    if type(doc.get("revision")) is not int or doc["revision"]<0:raise LedgerInvalid("LEDGER_REVISION")
    try:mode=RepoMode(doc.get("mode"))
    except Exception as exc:raise LedgerInvalid("LEDGER_MODE") from exc
    if type(doc.get("mode_version")) is not int or doc["mode_version"]<1:raise LedgerInvalid("LEDGER_MODE_VERSION")
    if type(doc.get("human_clear_required")) is not bool:raise LedgerInvalid("LEDGER_HUMAN_CLEAR")
    if mode in HUMAN_CLEAR_ONLY and doc["human_clear_required"] is not True:raise LedgerInvalid("LEDGER_HUMAN_CLEAR_REQUIRED")
    for key in ("leases","budgets","observations"):
        if not isinstance(doc.get(key),Mapping):raise LedgerInvalid(f"LEDGER_{key.upper()}")
    pe=doc.get("platform_enforcement")
    if not isinstance(pe,Mapping) or type(pe.get("branch_protected")) is not bool or type(pe.get("active_rulesets")) is not int or pe["active_rulesets"]<0:raise LedgerInvalid("LEDGER_PLATFORM_ENFORCEMENT")

def canonical_json(doc:Mapping[str,Any])->str:
    validate_ledger(doc)
    return json.dumps(doc,sort_keys=True,indent=2,separators=(",",": "))+"\n"

def blob_cas_ok(observed_blob_sha:str,expected_blob_sha:str)->bool:
    return isinstance(observed_blob_sha,str) and bool(observed_blob_sha) and observed_blob_sha==expected_blob_sha

def _begin(doc:Mapping[str,Any],expected_revision:int)->dict[str,Any]:
    validate_ledger(doc)
    if doc["revision"]!=expected_revision:raise LedgerConflict("LEDGER_REVISION_STALE")
    out=copy.deepcopy(dict(doc));out["revision"]+=1;return out

def cas_mode(doc:Mapping[str,Any],*,expected_revision:int,expected_mode_version:int,new_mode:RepoMode,human_clear:bool=False)->dict[str,Any]:
    out=_begin(doc,expected_revision)
    if out["mode_version"]!=expected_mode_version:raise LedgerConflict("MODE_VERSION_STALE")
    old=RepoMode(out["mode"])
    if old in HUMAN_CLEAR_ONLY and old!=new_mode and not human_clear:raise LedgerConflict("HUMAN_CLEAR_REQUIRED")
    out["mode"]=new_mode.value;out["mode_version"]+=1;out["human_clear_required"]=new_mode in HUMAN_CLEAR_ONLY
    validate_ledger(out);return out

def cas_lease(doc:Mapping[str,Any],key:str,*,expected_revision:int,expected_lease_version:int|None,new_record:Mapping[str,Any]|None)->dict[str,Any]:
    if not isinstance(key,str) or not key:raise LedgerInvalid("LEASE_KEY")
    out=_begin(doc,expected_revision);cur=out["leases"].get(key);actual=None if cur is None else cur.get("version")
    if actual!=expected_lease_version:raise LedgerConflict("LEASE_VERSION_STALE")
    if new_record is None:out["leases"].pop(key,None)
    else:
        row=copy.deepcopy(dict(new_record))
        if type(row.get("version")) is not int or row["version"]<1:raise LedgerInvalid("LEASE_RECORD_VERSION")
        if expected_lease_version is not None and row["version"]<=expected_lease_version:raise LedgerInvalid("LEASE_VERSION_NOT_MONOTONIC")
        out["leases"][key]=row
    validate_ledger(out);return out

def cas_budget(doc:Mapping[str,Any],key:str,*,expected_revision:int,expected_budget_version:int|None,new_record:Mapping[str,Any])->dict[str,Any]:
    out=_begin(doc,expected_revision);cur=out["budgets"].get(key);actual=None if cur is None else cur.get("version")
    if actual!=expected_budget_version:raise LedgerConflict("BUDGET_VERSION_STALE")
    row=copy.deepcopy(dict(new_record))
    if type(row.get("version")) is not int or row["version"]<1:raise LedgerInvalid("BUDGET_RECORD_VERSION")
    if expected_budget_version is not None and row["version"]<=expected_budget_version:raise LedgerInvalid("BUDGET_VERSION_NOT_MONOTONIC")
    out["budgets"][key]=row;validate_ledger(out);return out
