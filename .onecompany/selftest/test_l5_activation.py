from __future__ import annotations

import sys
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
    def __init__(self, *, boundaries=None, live=None, lost=False, effect=True):
        self.boundaries = boundaries or {k:False for k in act.HARD_BOUNDARY_FIELDS}
        self.live = live or {"head_sha":"a"*40,"base_sha":"b"*40,"pr_state":"open","open_streams":{262:[263]},"review_eligible_nonauthor":True}
        self.lost, self.effect, self.calls = lost, effect, 0
    def fetch_boundaries(self): return dict(self.boundaries)
    def fetch_live(self, _pr): return dict(self.live)
    def perform(self, _mutation, _params):
        self.calls += 1
        if self.lost: raise wa.LostResponse()
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
        first = act.authorize_mutation(snap())
        second = act.authorize_mutation(snap(event_id="poll-2"))
        self.assertEqual(first["mutation_token"], second["mutation_token"])
        replay = act.authorize_mutation(snap(event_id="poll-3"), prior_mutation_tokens={first["mutation_token"]})
        self.assertEqual(replay["reason"], "REPLAY_NOOP")

    def test_retry_attempts_have_distinct_tokens(self):
        first = act.authorize_mutation(snap(ci="FAILURE",review="UNKNOWN",event_id="r1"))
        second = act.authorize_mutation(snap(ci="FAILURE",review="UNKNOWN",retry_count=1,retry_action="CI",event_id="r2"))
        self.assertEqual(first["mutation"], "retry_ci")
        self.assertNotEqual(first["mutation_token"], second["mutation_token"])

    def test_live_cas_blocks_stale_head(self):
        s = snap(ci="FAILURE",review="UNKNOWN")
        auth = act.authorize_mutation(s)
        client = Client(live={"head_sha":"c"*40,"base_sha":"b"*40,"pr_state":"open","open_streams":{262:[263]},"review_eligible_nonauthor":True})
        out = wa.execute_mutation(auth,s,client,wa.MemoryStore())
        self.assertEqual(out["reason"], "STALE_HEAD_OR_BASE")
        self.assertEqual(client.calls,0)

    def test_boundary_rechecked_before_write(self):
        s = snap(ci="FAILURE",review="UNKNOWN")
        auth = act.authorize_mutation(s)
        class Flip(Client):
            def __init__(self): super().__init__(); self.n=0
            def fetch_boundaries(self):
                self.n += 1
                row = {k:False for k in act.HARD_BOUNDARY_FIELDS}
                if self.n > 1: row["emergency_stop"] = True
                return row
        client=Flip(); out=wa.execute_mutation(auth,s,client,wa.MemoryStore())
        self.assertEqual(out["reason"],"HARD_BOUNDARY"); self.assertEqual(client.calls,0)

    def test_lost_response_reconciles_without_duplicate_write(self):
        s=snap(ci="FAILURE",review="UNKNOWN"); auth=act.authorize_mutation(s); store=wa.MemoryStore(); client=Client(lost=True,effect=True)
        first=wa.execute_mutation(auth,s,client,store); second=wa.execute_mutation(auth,s,client,store)
        self.assertEqual(first["status"],"COMPLETE"); self.assertEqual(second["status"],"REPLAY_NOOP"); self.assertEqual(client.calls,1)

    def test_retry_state_is_per_stream(self):
        store=wa.MemoryStore()
        a=snap(ci="FAILURE",review="UNKNOWN"); aa=act.authorize_mutation(a); sa=wa.stream_key(aa,a)
        b=snap(issue=300,canonical_pr=301,active_prs=[301],ci="FAILURE",review="UNKNOWN",event_id="b"); ba=act.authorize_mutation(b); sb=wa.stream_key(ba,b)
        store.begin(aa["mutation_token"],{"status":"PENDING"},sa,1,"CI")
        store.begin(ba["mutation_token"],{"status":"PENDING"},sb,1,"CI")
        self.assertNotEqual(sa,sb); self.assertEqual(store.retry_state(sa),(1,"CI")); self.assertEqual(store.retry_state(sb),(1,"CI"))

    def test_provider_availability_never_grants_reviewer_eligibility(self):
        s=snap(review="UNKNOWN",reviewer_actor=None,review_eligible=False)
        auth=act.authorize_mutation(s)
        self.assertEqual(auth["mutation"],"dispatch_review")
        client=Client(live={"head_sha":"a"*40,"base_sha":"b"*40,"pr_state":"open","open_streams":{262:[263]},"review_eligible_nonauthor":False})
        self.assertEqual(wa.execute_mutation(auth,s,client,wa.MemoryStore())["reason"],"REVIEWER_NOT_ELIGIBLE")


if __name__ == "__main__": unittest.main()
