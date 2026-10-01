#!/usr/bin/env python3
"""Adversarial interleaving tests for Claude L5 coordination core."""
from __future__ import annotations
import random,sys
from dataclasses import replace
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from l5_kernel import *

CORE_SCENARIOS=("S1","S2","S3","S4","S21","S22")

def s1(rng):
    st=MemoryCASStore();obs=Observation("a"*40,"b"*40,"wu","t")
    l=acquire(st,repo_merge_lock_key("repo"),"A",obs,now_srv=0,ttl=5);assert l
    li=attach_intent(st,l,"repo","pr:1","merge");assert li
    assert fence_ok(st,"repo",li,replace(obs,pr_updated_at="human-change"),now_srv=10)[0] is False

def s2(rng):
    st=MemoryCASStore();obs=Observation("a"*40,"b"*40);key=lease_key("repo","pr","1","REPAIR")
    a=acquire(st,key,"run-A",obs,now_srv=0,ttl=300);assert a
    assert acquire(st,key,"run-B",obs,now_srv=rng.uniform(1,299),ttl=300) is None

def s3(rng):
    st=MemoryCASStore();obs=Observation("a"*40,"b"*40)
    l=acquire(st,repo_merge_lock_key("repo"),"A",obs,now_srv=0);li=attach_intent(st,l,"repo","pr:1","merge")
    assert intent_recovery(li,"UNKNOWN")=="READBACK_REQUIRED";assert intent_recovery(li,"APPLIED")=="RESOLVE_DONE"

def s4(rng):
    st=MemoryCASStore();obs=Observation("a"*40,"b"*40)
    l=acquire(st,lease_key("repo","pr","1","REPAIR"),"A",obs,now_srv=0);li=attach_intent(st,l,"repo","pr:1","push")
    assert intent_recovery(li,"UNKNOWN")=="READBACK_REQUIRED";assert intent_recovery(li,"APPLIED")=="RESOLVE_DONE"

def s21(rng):
    st=MemoryCASStore();obs=Observation("a"*40,"b"*40);key=lease_key("repo","wu","42","IMPLEMENT")
    hs=[f"run-{i}" for i in range(4)];rng.shuffle(hs);wins=[acquire(st,key,h,obs,now_srv=0) for h in hs]
    assert sum(x is not None for x in wins)==1

def s22(rng):
    st=MemoryCASStore();obs=Observation("a"*40,"b"*40);key=capacity_slot_key("repo",4)
    hs=[f"run-{i}" for i in range(4)];rng.shuffle(hs);wins=[acquire(st,key,h,obs,now_srv=0) for h in hs]
    assert sum(x is not None for x in wins)==1

SCENARIOS={"S1":s1,"S2":s2,"S3":s3,"S4":s4,"S21":s21,"S22":s22}
def run(rounds=1000,seed=0x5A17):
    rng=random.Random(seed);counts={k:0 for k in CORE_SCENARIOS}
    for sid in CORE_SCENARIOS:
        for _ in range(rounds):SCENARIOS[sid](rng);counts[sid]+=1
    return counts

def selftest():
    counts=run();assert all(v==1000 for v in counts.values());print("l5_hostile_sim PASS",counts)
if __name__=="__main__":selftest()
