#!/usr/bin/env python3
"""Resolve an executable dispatch/wake path for an already-routed actor."""
from __future__ import annotations

import argparse,json,sys
from ledger_lib import derive,ledger_enabled,list_events
from onecompany_lib import CONTROL,load_json

WRITE_CAPABILITIES={"implementation","ci_remediation"}

def main()->int:
    parser=argparse.ArgumentParser();parser.add_argument("--actor",required=True);parser.add_argument("--capability",required=True);parser.add_argument("--unattended",action="store_true");parser.add_argument("--lease-id");args=parser.parse_args()
    actors={i["id"]:i for i in load_json(CONTROL/"actors.json").get("actors",[]) if i.get("id")};readiness={i["actor_id"]:i for i in load_json(CONTROL/"readiness.json").get("actors",[]) if i.get("actor_id")};dispatch={i["actor_id"]:i for i in load_json(CONTROL/"dispatch.json").get("actors",[]) if i.get("actor_id")}
    actor=actors.get(args.actor);ready=readiness.get(args.actor);entry=dispatch.get(args.actor);reasons=[]
    if not actor:reasons.append("unknown_actor")
    else:
        if not actor.get("enabled") or not actor.get("configured"):reasons.append("actor_not_enabled_and_configured")
        if args.capability not in set(actor.get("capabilities",[])):reasons.append("capability_not_declared")
    if not ready:reasons.append("missing_readiness")
    else:
        if ready.get("setup_state") not in {"ready","degraded"}:reasons.append("actor_not_ready")
        if args.capability not in set(ready.get("verified_capabilities",[])):reasons.append("capability_not_verified")
        if args.capability in set(ready.get("temporarily_unavailable_capabilities",[])):reasons.append("capability_temporarily_unavailable")
        if args.unattended and (ready.get("unattended",{}).get("configured") is not True or ready.get("unattended",{}).get("verified") is not True):reasons.append("unattended_readiness_not_verified")
    if args.unattended and args.capability in WRITE_CAPABILITIES:
        if not ledger_enabled():reasons.append("durable_ledger_required_for_unattended_write")
        elif not args.lease_id:reasons.append("active_lease_id_required_for_unattended_write")
        else:
            try:
                view=derive(list_events());lease=next((x for x in view.get("active_leases",[]) if x.get("id")==args.lease_id),None)
                if not lease:reasons.append("lease_not_canonical_or_active")
                elif lease.get("actor")!=args.actor:reasons.append("lease_actor_mismatch")
            except Exception as exc:reasons.append(f"ledger_unavailable:{exc}")
    mechanisms=[]
    if entry:
        for m in entry.get("mechanisms",[]):
            if m.get("configured") and args.capability in set(m.get("capabilities",[])) and (not args.unattended or m.get("unattended")):
                mechanisms.append({"id":m.get("id"),"kind":m.get("kind"),"unattended":m.get("unattended"),"invocation_hint":m.get("invocation_hint"),"evidence":m.get("evidence",[])})
    else:reasons.append("missing_dispatch_record")
    if not mechanisms:reasons.append("no_configured_execution_mechanism")
    payload={"actor":args.actor,"capability":args.capability,"unattended_required":args.unattended,"status":"DISPATCH_READY" if not reasons and mechanisms else "CAPACITY_BLOCKED","mechanisms":mechanisms,"reasons":sorted(set(reasons))};print(json.dumps(payload,indent=2));return 0 if payload["status"]=="DISPATCH_READY" else 2
if __name__=="__main__":sys.exit(main())
