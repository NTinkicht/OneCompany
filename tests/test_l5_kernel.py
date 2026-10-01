#!/usr/bin/env python3
import sys, unittest
from dataclasses import replace
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from l5_kernel import *

def merge_snapshot():
    h="a"*40; b="b"*40
    src={"app_id":1,"workflow_path":".github/workflows/ci.yml"}; secsrc={"app_id":2,"workflow_path":".github/workflows/security.yml"}
    check={**src,"head_sha":h,"tested_base_sha":b,"latest_attempt":True,"conclusion":"success","assertion_failure_any_attempt":False}
    seccheck={**secsrc,"head_sha":h,"tested_base_sha":b,"latest_attempt":True,"conclusion":"success","assertion_failure_any_attempt":False}
    review={"state":"APPROVED","commit_id":h,"base_sha":b,"complete":True,"skipped":False,"covers_full_diff":True,"author":"coderabbitai","material_authors":["chatgpt"],"controller_identities":["controller-1"],"designated_independent":True}
    s={"head_sha":h,"base_sha":b,"expected_head_sha":h,"expected_base_sha":b,"repo_mode":"NORMAL","required_checks":[check],"security_checks":[seccheck],"required_check_sources":[src],"security_check_sources":[secsrc],"review":review}
    for k in TRUE_FIELDS:s[k]=True
    for k in FALSE_FIELDS:s[k]=False
    return s

class KernelTests(unittest.TestCase):
    def test_monotonic_epoch_and_pending_intent_blocks_reclaim(self):
        st=MemoryCASStore();o=Observation("a"*40,"b"*40);l=acquire(st,"k","r1",o,now_srv=1,ttl=5);self.assertIsNotNone(l);li=attach_intent(st,l,"repo","item","merge");self.assertIsNotNone(li);self.assertIsNone(acquire(st,"k","r2",o,now_srv=10,ttl=5));done=resolve_intent(st,li,"ABORTED");rel=release(st,done,now_srv=10);l2=acquire(st,"k","r2",o,now_srv=11,ttl=5);self.assertEqual(l2.epoch,l.epoch+1)
    def test_changed_observation_fails_fence(self):
        st=MemoryCASStore();o=Observation("a"*40,"b"*40);l=acquire(st,"k","r1",o,now_srv=1);li=attach_intent(st,l,"repo","item","merge");self.assertFalse(fence_ok(st,"repo",li,replace(o,head="c"*40),now_srv=2)[0])
    def test_ambiguous_write_requires_readback(self):
        st=MemoryCASStore();o=Observation("a"*40,"b"*40);l=acquire(st,"k","r1",o,now_srv=1);li=attach_intent(st,l,"repo","item","merge");self.assertEqual(intent_recovery(li,"UNKNOWN"),"READBACK_REQUIRED")
    def test_capacity_and_merge_locks_unique(self):
        for key in (repo_merge_lock_key("repo"),capacity_slot_key("repo",4)):
            st=MemoryCASStore();o=Observation("a"*40,"b"*40);self.assertEqual(sum(acquire(st,key,f"r{i}",o,now_srv=1) is not None for i in range(4)),1)
    def test_unprotected_is_governance_drift(self):
        self.assertEqual(governance_mode({"platform_enforcement_ok":False,"live_rules_at_least_pinned":True,"rulesets_or_protection_active":False,"required_check_sources_pinned":True}),RepoMode.GOVERNANCE_DRIFT)
    def test_ledger_outage_degrades_automation(self):self.assertEqual(governance_mode({"ledger_reachable":False}),RepoMode.AUTOMATION_DEGRADED)
    def test_merge_ok_full_predicate(self):self.assertEqual(merge_ok(merge_snapshot()),(True,()))
    def test_no_rerun_to_green(self):
        s=merge_snapshot();s["required_checks"][0]["assertion_failure_any_attempt"]=True;self.assertFalse(merge_ok(s)[0])
    def test_check_source_spoof_fails(self):
        s=merge_snapshot();s["required_checks"][0]["app_id"]=999;self.assertFalse(merge_ok(s)[0])
    def test_review_must_be_external_exact_head(self):
        s=merge_snapshot();s["review"]["author"]="chatgpt";self.assertFalse(merge_ok(s)[0]);s=merge_snapshot();s["review"]["commit_id"]="c"*40;self.assertFalse(merge_ok(s)[0])
    def test_unknown_gate_fails_closed(self):
        s=merge_snapshot();del s["files_fully_enumerated"];self.assertFalse(merge_ok(s)[0])
    def test_budget_parks_and_idle_quiesces(self):
        self.assertEqual(classify_item({"ci":"GREEN"},Budget(fix_iterations=MAX_FIX_ITERATIONS)),ItemState.PARKED);self.assertEqual(classify_item({"no_actionable_work":True},Budget()),ItemState.IDLE)
if __name__=="__main__":unittest.main()
