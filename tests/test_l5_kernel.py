#!/usr/bin/env python3
import sys
import unittest
from dataclasses import replace
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from l5_kernel import *

def merge_snapshot():
    h="a"*40;b="b"*40
    check={"head_sha":h,"tested_base_sha":b,"latest_attempt":True,"conclusion":"success","app_id":1,"workflow_path":".github/workflows/ci.yml","assertion_failure_any_attempt":False}
    review={"state":"APPROVED","commit_id":h,"base_sha":b,"complete":True,"skipped":False,"covers_full_diff":True,"author":"coderabbitai","material_authors":["chatgpt"],"controller_identities":["controller-1","controller-2"],"designated_independent":True}
    s={"head_sha":h,"base_sha":b,"expected_head_sha":h,"expected_base_sha":b,"repo_mode":"NORMAL","required_checks":[check],"security_checks":[{**check,"workflow_path":".github/workflows/security.yml"}],"review":review}
    for k in TRUE_FIELDS:s[k]=True
    for k in FALSE_FIELDS:s[k]=False
    return s

class KernelTests(unittest.TestCase):
    def test_monotonic_epoch_and_pending_intent_blocks_reclaim(self):
        st=MemoryCASStore();obs=Observation("a"*40,"b"*40)
        l=acquire(st,"k","r1",obs,now_srv=1,ttl=5); self.assertIsNotNone(l)
        li=attach_intent(st,l,"repo","item","merge"); self.assertIsNotNone(li)
        self.assertIsNone(acquire(st,"k","r2",obs,now_srv=10,ttl=5))
        done=resolve_intent(st,li,"ABORTED"); self.assertIsNotNone(done)
        rel=release(st,done,now_srv=10); self.assertIsNotNone(rel)
        l2=acquire(st,"k","r2",obs,now_srv=11,ttl=5); self.assertEqual(l2.epoch,l.epoch+1)
    def test_lost_lease_and_changed_observation_stop_write(self):
        st=MemoryCASStore();obs=Observation("a"*40,"b"*40)
        l=acquire(st,"k","r1",obs,now_srv=1);li=attach_intent(st,l,"repo","item","merge")
        self.assertTrue(fence_ok(st,"repo",li,obs,now_srv=2)[0])
        self.assertFalse(fence_ok(st,"repo",li,replace(obs,head="c"*40),now_srv=2)[0])
    def test_ambiguous_write_requires_readback(self):
        st=MemoryCASStore();obs=Observation("a"*40,"b"*40)
        l=acquire(st,"k","r1",obs,now_srv=1);li=attach_intent(st,l,"repo","item","merge")
        self.assertEqual(intent_recovery(li,"UNKNOWN"),"READBACK_REQUIRED")
    def test_capacity_slot_is_unique(self):
        st=MemoryCASStore();obs=Observation("a"*40,"b"*40);k=capacity_slot_key("repo",4)
        wins=[acquire(st,k,f"r{i}",obs,now_srv=1) for i in range(4)]
        self.assertEqual(sum(x is not None for x in wins),1)
    def test_repo_merge_lock_is_unique(self):
        st=MemoryCASStore();obs=Observation("a"*40,"b"*40);k=repo_merge_lock_key("repo")
        wins=[acquire(st,k,f"r{i}",obs,now_srv=1) for i in range(4)]
        self.assertEqual(sum(x is not None for x in wins),1)
    def test_governance_drift_when_unprotected(self):
        self.assertEqual(governance_mode({"platform_enforcement_ok":False,"live_rules_at_least_pinned":True,"rulesets_or_protection_active":False,"required_check_sources_pinned":True,"controller_admin":False,"controller_bypass":False}),RepoMode.GOVERNANCE_DRIFT)
    def test_merge_ok_full_predicate(self):
        s=merge_snapshot();self.assertEqual(merge_ok(s),(True,()))
        s["controller_bypass"]=True;ok,why=merge_ok(s);self.assertFalse(ok);self.assertIn("CONTROLLER_BYPASS_NOT_FALSE",why)
    def test_no_rerun_to_green(self):
        s=merge_snapshot();s["required_checks"][0]["assertion_failure_any_attempt"]=True
        ok,why=merge_ok(s);self.assertFalse(ok);self.assertIn("REQUIRED_CHECKS_INVALID",why)
    def test_review_must_be_external_exact_head(self):
        s=merge_snapshot();s["review"]["author"]="chatgpt";self.assertFalse(merge_ok(s)[0])
    def test_unknown_merge_datum_fails_closed(self):
        s=merge_snapshot();del s["files_fully_enumerated"];self.assertFalse(merge_ok(s)[0])
    def test_budget_parks(self):
        self.assertEqual(classify_item({"ci":"GREEN"},Budget(fix_iterations=MAX_FIX_ITERATIONS)),ItemState.PARKED)

if __name__=="__main__": unittest.main()
