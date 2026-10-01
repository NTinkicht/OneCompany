from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import l5_activation as act
import l5_write_adapter as wa


def snap(**patch):
    h, b = "a" * 40, "b" * 40
    row = {
        "repository":"NTinkicht/OneCompany","issue":262,"canonical_pr":263,"active_prs":[263],
        "head_sha":h,"base_sha":b,"head_current":True,"base_current":True,"implementation_complete":True,
        "emergency_stop":False,"human_only":False,"blocked":False,"release_go_no_go":False,
        "destructive_production":False,"spend_required":False,"secret_scope_change":False,"security_control_weakening":False,
        "merged":False,"verified":False,"verified_head_sha":None,"verified_base_sha":None,
        "ci":"SUCCESS","ci_head_sha":h,"ci_base_sha":b,"review":"PASS","review_head_sha":h,"review_base_sha":b,
        "reviewer_actor":"mistral-vibe","material_authors":["chatgpt"],"material_authors_head_sha":h,
        "review_eligible":True,"unresolved_threads":False,"mergeable":True,"retry_count":0,"retry_action":None,
        "event_id":"activation-1","ready_candidates":[],
    }
    row.update(patch); return row


class Client:
    def __init__(self, *, boundaries=None, live=None, effect=True):
        self.boundaries = boundaries or {k:False for k in act.HARD_BOUNDARY_FIELDS}
        self.live = live or {"head_sha":"a"*40,"base_sha":"b"*40,"pr_state":"open","open_streams":{262:[263]},"review_eligible_nonauthor":True}
        self.effect, self.calls = effect, 0
        self.reject = False; self.raise_unknown = False
    def fetch_boundaries(self): return dict(self.boundaries)
    def fetch_live(self, _pr): return dict(self.live)
    def perform_cas(self, _mutation, _params):
        self.calls += 1
        if self.reject: raise wa.WriteRejected("definitive no-write")
        if self.raise_unknown: raise RuntimeError("unknown after send")
        return True
    def verify_effect(self, _mutation, _params): return self.effect


class ActivationTests(unittest.TestCase):
    def test_merge_authorization_exact_refs(self):
        auth = act.authorize_mutation(snap())
        self.assertEqual(auth["mutation"], "merge_expected_head")
        self.assertTrue(auth["mutation_allowed"])
        self.assertEqual(auth["expected_head_sha"], "a"*40)

    def test_every_hard_boundary_blocks(self):
        for field in act.HARD_BOUNDARY_FIELDS:
            self.assertFalse(act.authorize_mutation(snap(**{field:True}))["mutation_allowed"], field)

    def test_event_replay_identity_is_stable(self):
        first = act.authorize_mutation(snap()); second = act.authorize_mutation(snap(event_id="poll-2"))
        self.assertEqual(first["mutation_token"], second["mutation_token"])
        replay = act.authorize_mutation(snap(event_id="poll-3"), prior_mutation_tokens={first["mutation_token"]})
        self.assertEqual(replay["reason"], "REPLAY_NOOP")

    def test_retry_attempts_have_distinct_tokens(self):
        first = act.authorize_mutation(snap(ci="FAILURE",review="UNKNOWN",event_id="r1"))
        second = act.authorize_mutation(snap(ci="FAILURE",review="UNKNOWN",retry_count=1,retry_action="CI",event_id="r2"))
        self.assertEqual(first["mutation"], "retry_ci"); self.assertNotEqual(first["mutation_token"], second["mutation_token"])

    def test_atomic_remote_cas_and_stale_head(self):
        s=snap(ci="FAILURE",review="UNKNOWN"); auth=act.authorize_mutation(s)
        client=Client(live={"head_sha":"c"*40,"base_sha":"b"*40,"pr_state":"open","open_streams":{262:[263]},"review_eligible_nonauthor":True})
        self.assertEqual(wa.execute_mutation(auth,s,client,wa.MemoryStore())["reason"],"STALE_HEAD_OR_BASE")
        client=Client(); client.perform_cas=None
        self.assertEqual(wa.execute_mutation(auth,s,client,wa.MemoryStore())["reason"],"ATOMIC_CAS_UNAVAILABLE")

    def test_merge_rechecks_reviewer_eligibility(self):
        s=snap(); auth=act.authorize_mutation(s); client=Client(); client.live["review_eligible_nonauthor"]=False
        out=wa.execute_mutation(auth,s,client,wa.MemoryStore())
        self.assertEqual(out["reason"],"REVIEWER_NOT_ELIGIBLE"); self.assertEqual(client.calls,0)

    def test_boundary_rechecked_before_write(self):
        s=snap(ci="FAILURE",review="UNKNOWN"); auth=act.authorize_mutation(s)
        class Flip(Client):
            def __init__(self): super().__init__(); self.n=0
            def fetch_boundaries(self):
                self.n += 1; row={k:False for k in act.HARD_BOUNDARY_FIELDS}
                if self.n > 1: row["emergency_stop"] = True
                return row
        client=Flip(); store=wa.MemoryStore(); out=wa.execute_mutation(auth,s,client,store)
        self.assertEqual(out["reason"],"HARD_BOUNDARY"); self.assertEqual(client.calls,0)
        self.assertEqual(store.retry_state(wa.stream_key(auth,s)),(0,None))
        self.assertEqual(store.get(auth["mutation_token"])["status"],"RETRYABLE")

    def test_uncertain_write_stays_pending_then_reconciles(self):
        s=snap(ci="FAILURE",review="UNKNOWN"); auth=act.authorize_mutation(s); store=wa.MemoryStore(); client=Client(effect=False); client.raise_unknown=True
        first=wa.execute_mutation(auth,s,client,store)
        self.assertEqual(first["status"],"IN_PROGRESS"); self.assertEqual(store.get(auth["mutation_token"])["status"],"PENDING")
        client.raise_unknown=False; client.effect=True
        second=wa.execute_mutation(auth,s,client,store)
        self.assertEqual(second["status"],"COMPLETE"); self.assertEqual(client.calls,1)

    def test_definitive_rejection_is_retryable(self):
        s=snap(ci="FAILURE",review="UNKNOWN"); auth=act.authorize_mutation(s); store=wa.MemoryStore(); client=Client(); client.reject=True
        first=wa.execute_mutation(auth,s,client,store)
        self.assertEqual(first["reason"],"WRITE_REJECTED"); self.assertEqual(store.get(auth["mutation_token"])["status"],"RETRYABLE")
        self.assertEqual(store.retry_state(wa.stream_key(auth,s)),(0,None))
        client.reject=False
        self.assertEqual(wa.execute_mutation(auth,s,client,store)["status"],"COMPLETE")

    def test_retry_restore_cas_preserves_newer_state(self):
        store=wa.MemoryStore(); token="1"*64
        self.assertTrue(store.begin(token,{"status":"PENDING"},"stream",1,"CI",expected_retry=(0,None)))
        store.retry["stream"]=(2,"CI"); store.fail_and_restore(token,"late","stream",(0,None))
        self.assertEqual(store.retry_state("stream"),(2,"CI"))

    def test_retry_state_cas_blocks_stale_concurrent_authorization(self):
        store=wa.MemoryStore(); observed=(0,None)
        self.assertTrue(store.begin("2"*64,{"status":"PENDING"},"stream",1,"CI",expected_retry=observed))
        self.assertFalse(store.begin("3"*64,{"status":"PENDING"},"stream",1,"CI",expected_retry=observed))

    def test_json_store_persists_token_and_retry_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"l5-store.json"; store=wa.JsonFileStore(path)
            self.assertTrue(store.begin("4"*64,{"status":"PENDING"},"stream",1,"CI",expected_retry=(0,None)))
            reopened=wa.JsonFileStore(path)
            self.assertEqual(reopened.get("4"*64)["status"],"PENDING"); self.assertEqual(reopened.retry_state("stream"),(1,"CI"))

    def test_provider_availability_never_grants_reviewer_eligibility(self):
        s=snap(review="UNKNOWN",reviewer_actor=None,review_eligible=False); auth=act.authorize_mutation(s)
        client=Client(live={"head_sha":"a"*40,"base_sha":"b"*40,"pr_state":"open","open_streams":{262:[263]},"review_eligible_nonauthor":False})
        self.assertEqual(wa.execute_mutation(auth,s,client,wa.MemoryStore())["reason"],"REVIEWER_NOT_ELIGIBLE")


if __name__ == "__main__": unittest.main()
