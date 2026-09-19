"""Pure policy gate: hostile model arguments, lost leases, and stale refs."""
from __future__ import annotations
import dataclasses
import datetime as dt
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from write_policy import WriteRequest, WriteRefused, scoped_path, verify_write_contract

NOW = dt.datetime(2026, 9, 19, 12, 0, tzinfo=dt.timezone.utc)
HEAD = "a" * 40
BASE = "b" * 40
REPO = "NTinkicht/OneCompany"

def fixture():
    request = WriteRequest("grok-4-6-interactive", "WU-SMOKE", "lease-one",
                           106, HEAD, "services/github_app_adapter/smoke.py",
                           "print('hello')\n")
    lease = {"id": "lease-one", "actor": "grok-4-6-interactive",
             "role": "implementation", "status": "active",
             "work_unit": "WU-SMOKE", "branch": "wu-grok-smoke", "pr": 106,
             "expires_at": "2026-09-19T14:00:00Z",
             "admission_snapshot": {
                 "schema": "onecompany-lease-admission-v1",
                 "actor": "grok-4-6-interactive", "actor_eligible": True,
                 "dependencies_complete": True, "trusted_ref": BASE}}
    work = {"id": "WU-SMOKE", "branch": "wu-grok-smoke", "pr": 106,
            "status": "READY",
            "write_scope": ["services/github_app_adapter/*.py"]}
    pr = {"number": 106, "state": "open", "merged_at": None,
          "head": {"ref": "wu-grok-smoke", "sha": HEAD,
                   "repo": {"full_name": REPO}},
          "base": {"ref": "main", "sha": BASE,
                   "repo": {"full_name": REPO}}}
    config = {"project": {"repository": REPO, "default_branch": "main"},
              "autonomy": {"level": "L1"},
              "safety": {"emergency_stop": False}}
    return dict(request=request, lease=lease, work_item=work, pr=pr,
                main_sha=BASE, config=config, now=NOW, feature_enabled=True,
                independently_verified_ledger=True,
                independently_verified_base=True,
                independently_verified_app=True)

class WritePolicyTests(unittest.TestCase):
    def refuse(self, data, reason):
        with self.assertRaisesRegex(WriteRefused, reason):
            verify_write_contract(**data)

    def test_positive_contract_does_not_claim_actual_mutation(self):
        verified = verify_write_contract(**fixture())
        self.assertTrue(verified["safe_to_recheck_before_exact_ref_cas"])
        self.assertFalse(verified["authority_from_model_arguments"])

    def test_all_authority_flags_and_emergency_stop_fail_closed(self):
        for key in ("feature_enabled", "independently_verified_ledger",
                    "independently_verified_base", "independently_verified_app"):
            with self.subTest(key=key):
                data=fixture()
                data[key]=False
                self.refuse(data, "writer_disabled" if key=="feature_enabled" else "writer_authority_unverified")
        data=fixture()
        data["config"]["safety"]["emergency_stop"]=True
        self.refuse(data,"emergency_stop")

    def test_lease_and_actor_never_inferred_from_pr_text(self):
        for key,value in (("actor","NTinkicht"),("lease_id","wrong"),
                          ("pr_number",102),("work_unit","WU-OTHER"),
                          ("expected_head_sha","c"*40)):
            data=fixture()
            data["request"]=dataclasses.replace(data["request"], **{key:value})
            self.refuse(data, "invalid|mismatch|changed")
        data=fixture(); data["lease"]["status"]="transferred"
        self.refuse(data,"lease_mismatch")
        data=fixture(); data["lease"]["expires_at"]="2026-09-19T11:00:00Z"
        self.refuse(data,"lease_expired")
        data=fixture(); data["lease"]["admission_snapshot"]["trusted_ref"]="c"*40
        self.refuse(data,"admission_unverified")

    def test_stale_pr_branch_base_and_scope_fail(self):
        for part,key,value in (
            ("pr","state","closed"),("work_item","pr",123),
            ("work_item","write_scope",["docs/**"]),
        ):
            data=fixture()
            data[part][key]=value
            self.refuse(data,"changed|binding|scope")
        data=fixture(); data["pr"]["head"]["sha"]="d"*40
        self.refuse(data,"head_or_base_changed")
        data=fixture(); data["pr"]["base"]["sha"]="d"*40
        self.refuse(data,"head_or_base_changed")
        data=fixture(); data["config"]["project"]["repository"]="NTinkicht/Tabibi"
        self.refuse(data,"repository_or_base_mismatch")

    def test_forbid_controls_credentials_and_large_content(self):
        self.assertFalse(scoped_path(".onecompany/ledger.json",["**/*"]))
        self.assertFalse(scoped_path(".github/workflows/ci.yml",["**/*"]))
        self.assertFalse(scoped_path("docs/secret-token.md",["docs/**"]))
        self.assertFalse(scoped_path("docs/../README.md",["docs/**"]))
        data=fixture();data["request"]=dataclasses.replace(data["request"],content="x"*36_001)
        self.refuse(data,"write_request_invalid")

if __name__ == "__main__":
    unittest.main()
