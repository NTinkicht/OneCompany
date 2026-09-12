#!/usr/bin/env python3
"""Explicit OneCompany implementation leases with durable-ledger race protection."""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import uuid

from ledger_lib import derive, ledger_enabled, list_events, post_event
from onecompany_lib import CONTROL, active_implementation_leases, budget_allows, load_json, save_json


def actor_eligible_for_implementation(actor_id: str) -> tuple[bool, list[str]]:
    actors=load_json(CONTROL/"actors.json"); readiness_doc=load_json(CONTROL/"readiness.json"); budget=load_json(CONTROL/"budget.json")
    actor=next((i for i in actors.get("actors",[]) if i.get("id")==actor_id),None); ready=next((i for i in readiness_doc.get("actors",[]) if i.get("actor_id")==actor_id),None); reasons=[]
    if actor is None:return False,["unknown_actor"]
    if not actor.get("enabled"):reasons.append("disabled")
    if not actor.get("configured"):reasons.append("not_configured")
    if "implementation" not in actor.get("capabilities",[]):reasons.append("implementation_not_declared")
    if not budget_allows(actor.get("cost_class","UNKNOWN_COST"),budget):reasons.append("forbidden_by_budget")
    if ready is None:reasons.append("missing_readiness")
    else:
        if ready.get("setup_state") not in {"ready","degraded"}:reasons.append(f"setup_state:{ready.get('setup_state')}")
        if "implementation" not in ready.get("verified_capabilities",[]):reasons.append("implementation_not_verified")
        if "implementation" in ready.get("temporarily_unavailable_capabilities",[]):reasons.append("implementation_temporarily_unavailable")
        access=ready.get("repository_access",{})
        if not access.get("read"):reasons.append("repository_read_not_verified")
        if not access.get("write"):reasons.append("repository_write_not_verified")
    return not reasons,reasons


def new_lease(actor:str,wu:str,branch:str,pr:int|None,start_head:str,parent_lease_id:str|None=None)->dict:
    value={"id":str(uuid.uuid4()),"work_unit":wu,"role":"implementation","actor":actor,"branch":branch,"pr":pr,"start_head":start_head,"status":"active","granted_at":dt.datetime.now(dt.timezone.utc).isoformat(),"failover_conditions":["quota_exhausted","unavailable","no_durable_progress_after_reconciliation","human_override"]}
    if parent_lease_id:value["parent_lease_id"]=parent_lease_id
    return value


def lease_payload(lease:dict)->dict:
    return {"lease_id":lease.get("id"),"role":lease.get("role"),"work_unit":lease.get("work_unit"),"branch":lease.get("branch"),"pr":lease.get("pr"),"start_head":lease.get("start_head"),"parent_lease_id":lease.get("parent_lease_id")}


def authoritative(state:dict)->tuple[list[dict],list[dict]]:
    if ledger_enabled():
        view=derive(list_events()); return [x for x in view.get("active_leases",[]) if x.get("role")=="implementation"],view.get("conflicts",[])
    return active_implementation_leases(state),[]


def sync_cache(state:dict,pr:int|None)->None:
    if not ledger_enabled():return
    events=list_events(); global_view=derive(events); state["active_leases"]=global_view.get("active_leases",[])
    if pr is not None:
        pr_view=derive(events,pr); state["current_material_authors"]=pr_view.get("material_authors",[]); state["current_gate"]=pr_view.get("current_gate")


def acquire(args)->int:
    state=load_json(CONTROL/"state.json")
    if ledger_enabled() and args.pr is None:
        print("REFUSED: durable autonomous implementation lease requires a PR number; open a draft/canonical PR first");return 2
    active,_=authoritative(state)
    if active:print(f"REFUSED: implementation lease already active for {active[0].get('work_unit')} by {active[0].get('actor')}");return 2
    eligible,reasons=actor_eligible_for_implementation(args.actor)
    if not eligible:print(f"REFUSED: actor {args.actor} is not implementation-ready: {','.join(reasons)}");return 2
    lease=new_lease(args.actor,args.wu,args.branch,args.pr,args.start_head)
    if ledger_enabled():
        try:
            post_event("ROLE_LEASE_ASSIGNED",args.actor,lease_payload(lease)); view=derive(list_events()); winner=next((x for x in view.get("active_leases",[]) if x.get("role")=="implementation"),None)
            if not winner or winner.get("id")!=lease.get("id"):
                print(f"REFUSED: lease lost a concurrent claim race; canonical winner={winner.get('id') if winner else None}");return 2
        except Exception as exc:print(f"REFUSED: durable lease record failed: {exc}");return 2
    state.setdefault("active_leases",[]).append(lease); authors=state.setdefault("current_material_authors",[])
    if args.actor not in authors:authors.append(args.actor)
    state["current_work_unit"]=args.wu
    if args.pr is not None:state["current_pr"]=args.pr;state["current_pr_head"]=args.start_head
    state["current_gate"]=None;state["company_state"]="ACTIVE_IMPLEMENTATION";sync_cache(state,args.pr);save_json(CONTROL/"state.json",state);print(f"LEASED {args.wu} to {args.actor} on {args.branch} ({lease['id']})");return 0


def release(args)->int:
    state=load_json(CONTROL/"state.json");active,_=authoritative(state);old=next((x for x in active if x.get("id")==args.lease_id),None)
    if not old:print("REFUSED: active lease not found");return 2
    if ledger_enabled():
        try:post_event("ROLE_LEASE_RELEASED",str(old.get("actor") or "system"),{"lease_id":args.lease_id,"pr":old.get("pr"),"reason":args.reason})
        except Exception as exc:print(f"REFUSED: durable lease release failed: {exc}");return 2
    for lease in state.get("active_leases",[]):
        if lease.get("id")==args.lease_id and lease.get("status")=="active":lease["status"]="released";lease["released_at"]=dt.datetime.now(dt.timezone.utc).isoformat();lease["release_reason"]=args.reason
    sync_cache(state,old.get("pr"));save_json(CONTROL/"state.json",state);print("LEASE RELEASED");return 0


def transfer(args)->int:
    state=load_json(CONTROL/"state.json");active,_=authoritative(state)
    if len(active)!=1:print(f"REFUSED: transfer requires exactly one active implementation lease; found {len(active)}");return 2
    old=active[0];eligible,reasons=actor_eligible_for_implementation(args.actor)
    if not eligible:print(f"REFUSED: replacement actor {args.actor} is not implementation-ready: {','.join(reasons)}");return 2
    if old.get("actor")==args.actor:print("REFUSED: replacement actor already holds lease");return 2
    replacement=new_lease(args.actor,str(old.get("work_unit")),str(old.get("branch")),old.get("pr"),args.current_head,str(old.get("id")));payload=lease_payload(replacement)|{"old_lease_id":old.get("id"),"new_lease_id":replacement.get("id"),"old_actor":old.get("actor"),"reason":args.reason}
    if ledger_enabled():
        try:
            post_event("ROLE_LEASE_TRANSFERRED",args.actor,payload);view=derive(list_events());winner=next((x for x in view.get("active_leases",[]) if x.get("role")=="implementation"),None)
            if not winner or winner.get("id")!=replacement.get("id"):print("REFUSED: durable transfer did not become canonical");return 2
        except Exception as exc:print(f"REFUSED: durable failover record failed: {exc}");return 2
    now=dt.datetime.now(dt.timezone.utc).isoformat()
    for lease in state.get("active_leases",[]):
        if lease.get("id")==old.get("id") and lease.get("status")=="active":lease["status"]="released";lease["released_at"]=now;lease["release_reason"]=args.reason
    state.setdefault("active_leases",[]).append(replacement);authors=state.setdefault("current_material_authors",[])
    if args.actor not in authors:authors.append(args.actor)
    state["current_pr_head"]=args.current_head if old.get("pr") is not None else state.get("current_pr_head");state["current_gate"]=None;state["company_state"]="ACTIVE_IMPLEMENTATION";sync_cache(state,old.get("pr"));save_json(CONTROL/"state.json",state);print(f"LEASE FAILOVER {old.get('actor')} -> {args.actor}; WU={old.get('work_unit')} branch={old.get('branch')} pr={old.get('pr')}");print(f"NEW LEASE {replacement['id']}");return 0


def main()->int:
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest="command",required=True);a=sub.add_parser("acquire");a.add_argument("--wu",required=True);a.add_argument("--actor",required=True);a.add_argument("--branch",required=True);a.add_argument("--start-head",required=True);a.add_argument("--pr",type=int);a.set_defaults(func=acquire);r=sub.add_parser("release");r.add_argument("--lease-id",required=True);r.add_argument("--reason",default="completed_or_failover");r.set_defaults(func=release);t=sub.add_parser("transfer");t.add_argument("--actor",required=True);t.add_argument("--current-head",required=True);t.add_argument("--reason",default="capability_failover");t.set_defaults(func=transfer);args=p.parse_args();return args.func(args)
if __name__=="__main__":sys.exit(main())
