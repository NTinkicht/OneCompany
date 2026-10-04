from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

# This acceptance test validates the OneCompany source repository's pinned L5
# reviewer/credential trust policy. Fresh bootstrap targets intentionally do
# not inherit that source authority; in those targets the production gate
# remains fail-closed until a target-specific policy is established.
if not (ROOT / ".l5" / "trust-policy.json").exists():
    raise unittest.SkipTest("source L5 trust policy is not installed in this fresh target")

import l5_activation as act
import l5_trust_boundary as tb
import l5_write_adapter as wa

ACTIVE_CONTROL_PLANE = ROOT / "tests" / "fixtures" / "l5-control-plane-active.json"


def _credential_boundary():
    return {
        "controller_executes_repository_code":False,
        "test_worker_has_write_token":False,
        "write_token_in_test_env":False,
        "actuator_executes_repository_code":False,
        "repo_code_runs_in_actuator":False,
        "actuator_accepts_structured_only":True,
        "credential_boundary_verified":True,
    }


def snap(**patch):
    h, b = "a" * 40, "b" * 40
    policy = tb.load_trust_policy()
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
        "trust_review":{
            "state":"APPROVED","commit_id":h,"base_sha":b,"complete":True,"skipped":False,
            "covers_full_diff":True,"identity_source_verified":True,"author":"mistral-vibe",
        },
        "credential_boundary":_credential_boundary(),
        "trust_policy_hash":policy.policy_hash,
    }
    row.update(patch); return row


class Client:
    def __init__(self, *, boundaries=None, live=None, lost=False, effect=True):
        self.boundaries = boundaries or {k:False for k in act.HARD_BOUNDARY_FIELDS}
        self.live = live or {"head_sha":"a"*40,"base_sha":"b"*40,"pr_state":"open","open_streams":{262:[263]},"review_eligible_nonauthor":True}
        self.lost, self.effect, self.calls = lost, effect, 0
        self.reject = False
    def fetch_boundaries(self): return dict(self.boundaries)
    def fetch_live(self, _pr): return dict(self.live)
    def perform_cas(self, _mutation, _params):
        self.calls += 1
        if self.reject:
            raise wa.WriteRejected("definitive no-write")
        if self.lost:
            raise wa.LostResponse()
        return True
    def verify_effect(self, _mutation, _params): return self.effect


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self._old_control_plane = os.environ.get("L5_CONTROL_PLANE_MANIFEST")
        os.environ["L5_CONTROL_PLANE_MANIFEST"] = str(ACTIVE_CONTROL_PLANE)
        # The fixture is synthetic. Real runtime attestation is covered by the
        # bootstrap/control-plane suites, so downstream authorization tests
        # mock bootstrap refresh, exact-ref attestation, and the adapter's
        # activation reload only at this synthetic CAS boundary.
        self._bootstrap_patch = mock.patch.object(act, "bootstrap_runtime", return_value=(True, "TEST_ATTESTED"))
        self._attestation_patch = mock.patch.object(act._bootstrap_module, "active_attestation_matches", return_value=True)
        self._activation_reload_patch = mock.patch.object(wa, "_refresh_activation_api", return_value=act)
        self._bootstrap_mock = self._bootstrap_patch.start()
        self._attestation_patch.start()
        self._activation_reload_patch.start()

    def tearDown(self):
        self._activation_reload_patch.stop()
        self._attestation_patch.stop()
        self._bootstrap_patch.stop()
        if self._old_control_plane is None:
            os.environ.pop("L5_CONTROL_PLANE_MANIFEST", None)
        else:
            os.environ["L5_CONTROL_PLANE_MANIFEST"] = self._old_control_plane

    def test_lazy_import_revalidates_bootstrap(self):
        before = self._bootstrap_mock.call_count
        act._recovery_api()
        self.assertGreater(self._bootstrap_mock.call_count, before)

    def test_cached_control_plane_module_is_discarded(self):
        fake = type(sys)("l5_control_plane")
        fake.called = False

        def hostile(_operation):
            fake.called = True
            return True, "HOSTILE"

        fake.mutation_policy = hostile
        prior = sys.modules.get("l5_control_plane")
        sys.modules["l5_control_plane"] = fake
        try:
            act._control_plane_policy(None)
            self.assertFalse(fake.called)
        finally:
            if prior is None:
                sys.modules.pop("l5_control_plane", None)
            else:
                sys.modules["l5_control_plane"] = prior

    def test_active_policy_requires_matching_bootstrap_attestation(self):
        with mock.patch.object(act._bootstrap_module, "active_attestation_matches", return_value=False):
            auth = act.authorize_mutation(snap())
        self.assertFalse(auth["mutation_allowed"])
        self.assertEqual(auth["reason"], "CONTROL_PLANE_BOOTSTRAP_ATTESTATION_MISSING")

    def test_merge_authorization_exact_refs(self):
        auth = act.authorize_mutation(snap())
        self.assertEqual(auth["mutation"], "merge_expected_head")
        self.assertTrue(auth["mutation_allowed"])
        self.assertEqual(auth["expected_head_sha"], "a"*40)

    def test_merge_authorization_requires_pinned_trust_boundary(self):
        s = snap(trust_policy_hash="0"*64)
        auth = act.authorize_mutation(s)
        self.assertFalse(auth["mutation_allowed"])
        self.assertEqual(auth["reason"], "TRUST_BOUNDARY_FAILED")

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

    def test_atomic_remote_cas_is_mandatory(self):
        s = snap(ci="FAILURE",review="UNKNOWN")
        auth = act.authorize_mutation(s)
        client = Client(); client.perform_cas = None
        out = wa.execute_mutation(auth,s,client,wa.MemoryStore())
        self.assertEqual(out["reason"], "ATOMIC_CAS_UNAVAILABLE")
        self.assertEqual(client.calls,0)

    def test_merge_rechecks_nonauthor_reviewer(self):
        s = snap(); auth = act.authorize_mutation(s); client = Client()
        client.live["review_eligible_nonauthor"] = False
        out = wa.execute_mutation(auth,s,client,wa.MemoryStore())
        self.assertEqual(out["reason"], "REVIEWER_NOT_ELIGIBLE")
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
        client=Flip(); store=wa.MemoryStore(); out=wa.execute_mutation(auth,s,client,store)
        self.assertEqual(out["reason"],"HARD_BOUNDARY"); self.assertEqual(client.calls,0)
        self.assertEqual(store.retry_state(wa.stream_key(auth,s)),(0,None))
        self.assertEqual(store.get(auth["mutation_token"])["status"],"RETRYABLE")

    def test_lost_response_reconciles_without_duplicate_write(self):
        s=snap(ci="FAILURE",review="UNKNOWN"); auth=act.authorize_mutation(s); store=wa.MemoryStore(); client=Client(lost=True,effect=True)
        first=wa.execute_mutation(auth,s,client,store); second=wa.execute_mutation(auth,s,client,store)
        self.assertEqual(first["status"],"COMPLETE"); self.assertEqual(second["status"],"REPLAY_NOOP"); self.assertEqual(client.calls,1)

    def test_uncertain_write_stays_pending_until_effect_is_visible(self):
        s=snap(ci="FAILURE",review="UNKNOWN"); auth=act.authorize_mutation(s); store=wa.MemoryStore(); client=Client(lost=True,effect=False)
        first=wa.execute_mutation(auth,s,client,store)
        self.assertEqual(first["status"],"IN_PROGRESS")
        self.assertEqual(store.get(auth["mutation_token"])["status"],"PENDING")
        client.effect=True
        second=wa.execute_mutation(auth,s,client,store)
        self.assertEqual(second["status"],"COMPLETE")
        self.assertEqual(client.calls,1)

    def test_unexpected_perform_exception_reconciles_without_refund(self):
        s=snap(ci="FAILURE",review="UNKNOWN"); auth=act.authorize_mutation(s); store=wa.MemoryStore()
        class Boom(Client):
            def perform_cas(self, _mutation, _params):
                self.calls += 1
                raise RuntimeError("transport failed after send")
        client=Boom(effect=True); out=wa.execute_mutation(auth,s,client,store)
        self.assertEqual(out["status"],"COMPLETE")
        self.assertEqual(store.retry_state(wa.stream_key(auth,s)),(1,"CI"))
        self.assertEqual(client.calls,1)

    def test_definitive_no_write_rejection_can_retry_same_merge_token(self):
        s=snap(); auth=act.authorize_mutation(s); store=wa.MemoryStore(); client=Client(); client.reject=True
        first=wa.execute_mutation(auth,s,client,store)
        self.assertEqual(first["reason"],"WRITE_REJECTED")
        self.assertEqual(store.get(auth["mutation_token"])["status"],"RETRYABLE")
        client.reject=False
        second=wa.execute_mutation(auth,s,client,store)
        self.assertEqual(second["status"],"COMPLETE")

    def test_retry_state_cas_blocks_stale_concurrent_authorization(self):
        store=wa.MemoryStore(); s=snap(ci="FAILURE",review="UNKNOWN"); auth=act.authorize_mutation(s); stream=wa.stream_key(auth,s)
        observed=store.retry_state(stream)
        self.assertTrue(store.begin("1"*64,{"status":"PENDING"},stream,1,"CI",expected_retry=observed))
        self.assertFalse(store.begin("2"*64,{"status":"PENDING"},stream,1,"CI",expected_retry=observed))
        self.assertEqual(store.retry_state(stream),(1,"CI"))

    def test_token_owner_prevents_retry_aba_restore(self):
        store=wa.MemoryStore(); stream="s"; old="1"*64; newer="2"*64
        self.assertTrue(store.begin(old,{"status":"PENDING"},stream,1,"CI",expected_retry=(0,None),expected_owner=None))
        self.assertTrue(store.begin(newer,{"status":"PENDING"},stream,1,"REVIEW",expected_retry=(1,"CI"),expected_owner=old))
        store.fail_and_restore(newer,"newer failed",stream,(1,"CI"))
        self.assertEqual(store.retry_state(stream),(1,"CI")); self.assertEqual(store.retry_owner(stream),newer)
        store.fail_and_restore(old,"old late",stream,(0,None))
        self.assertEqual(store.retry_state(stream),(1,"CI")); self.assertEqual(store.retry_owner(stream),newer)

    def test_json_store_persists_token_retry_state_and_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"l5-store.json"; store=wa.JsonFileStore(path); token="3"*64
            self.assertTrue(store.begin(token,{"status":"PENDING"},"stream",1,"CI",expected_retry=(0,None),expected_owner=None))
            reopened=wa.JsonFileStore(path)
            self.assertEqual(reopened.get(token)["status"],"PENDING")
            self.assertEqual(reopened.retry_state("stream"),(1,"CI"))
            self.assertEqual(reopened.retry_owner("stream"),token)

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
