"""Exact-ref writer remains dark; verify token scope and no-force ref CAS."""
from __future__ import annotations
import dataclasses
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from writer_git import ExactRefWriter
from write_policy import WriteRequest, WriteRefused
from github_app import AppClient, AdapterRefused
from settings import Settings

REPO="NTinkicht/OneCompany"
HEAD="a"*40
BASE="b"*40
NEW="c"*40

def conf():
    return Settings(True,"x"*42,5003121,163077002,Path("/not-present"),
                    REPO,"onecompany-github-adapter.onrender.com")

class WriterFake(AppClient):
    def __init__(self):
        super().__init__(conf())
        self.calls=[]
        self.current=HEAD
        self.grant=True
    def _jwt(self):return "dummy-APP-JWT"
    def _call(self,method,path,token,payload=None):
        self.calls.append((method,path,payload))
        if path=="/app":return {"id":5003121,"slug":"onecompany-grok-worker"}
        if path==f"/repos/{REPO}/installation":return {"id":163077002}
        if path.endswith("/access_tokens"):
            perms={"contents":"write","pull_requests":"read","issues":"read"}
            if not self.grant:perms["contents"]="read"
            return {"token":"z"*48,"permissions":perms,
                    "repository_selection":"selected",
                    "repositories":[{"full_name":REPO}]}
        if path==f"/repos/{REPO}/pulls/106":
            return {"head":{"sha":self.current,"ref":"wu-grok-smoke",
                    "repo":{"full_name":REPO}},
                    "base":{"sha":BASE,"ref":"main","repo":{"full_name":REPO}}}
        if path.startswith(f"/repos/{REPO}/contents/"):
            return {"type":"file","sha":"d"*40}
        if path==f"/repos/{REPO}/git/commits/{HEAD}":
            return {"tree":{"sha":"e"*40}}
        if path==f"/repos/{REPO}/git/blobs":
            return {"sha":"f"*40}
        if path==f"/repos/{REPO}/git/trees":
            return {"sha":"9"*40}
        if path==f"/repos/{REPO}/git/commits":
            return {"sha":NEW}
        if method=="PATCH":
            self.current=payload["sha"]
            return {"object":{"sha":self.current}}
        raise AssertionError((method,path))

def request():
    return WriteRequest("grok-4-6-interactive","WU-SMOKE","lease-1",
                        106,HEAD,"services/github_app_adapter/smoke.py",
                        "print('hello')\n")

class ExactRefWriterTests(unittest.TestCase):
    def test_writer_is_default_off_without_any_github_calls(self):
        client=WriterFake()
        writer=ExactRefWriter(client)
        with patch.dict(os.environ,{"ONECOMPANY_GROK_WRITE_ENABLED":"false"}):
            with self.assertRaisesRegex(WriteRefused,"writer_disabled"):
                writer.submit(request(),"d"*40)
        self.assertEqual(client.calls,[])

    def test_write_token_is_one_repo_with_narrow_permissions(self):
        client=WriterFake()
        writer=ExactRefWriter(client)
        self.assertEqual(writer._write_token(),"z"*48)
        mint=next(x for x in client.calls if x[1].endswith("/access_tokens"))
        self.assertEqual(mint[2],{
            "repositories":["OneCompany"],
            "permissions":{"contents":"write","pull_requests":"read","issues":"read"},
        })
        client=WriterFake();client.grant=False
        with self.assertRaisesRegex(WriteRefused,"scope_unverified"):
            ExactRefWriter(client)._write_token()

    def test_exact_ref_mutation_is_never_forced(self):
        client=WriterFake()
        writer=ExactRefWriter(client)
        with patch.object(writer.authority,"inspect",return_value={
            "branch":"wu-grok-smoke","expected_head_sha":HEAD,
            "main_sha":BASE}):
            with patch.dict(os.environ,{"ONECOMPANY_GROK_WRITE_ENABLED":"true"}):
                result=writer.submit(request(),"d"*40)
        self.assertEqual(result["new_head"],NEW)
        refs=[x for x in client.calls if x[0]=="PATCH"]
        self.assertEqual(len(refs),1)
        self.assertEqual(refs[0][1],
             f"/repos/{REPO}/git/refs/heads/wu-grok-smoke")
        self.assertEqual(refs[0][2],{"sha":NEW,"force":False})
        self.assertEqual(client.current,NEW)

    def test_wrong_blob_or_stale_head_prevents_ref_mutation(self):
        for changed in (False,True):
            client=WriterFake()
            if changed:client.current="1"*40
            writer=ExactRefWriter(client)
            with patch.object(writer.authority,"inspect",return_value={
                "branch":"wu-grok-smoke","expected_head_sha":HEAD,
                "main_sha":BASE}):
                with patch.dict(os.environ,{"ONECOMPANY_GROK_WRITE_ENABLED":"true"}):
                    with self.assertRaisesRegex(
                        WriteRefused,
                        "head_changed|blob_cas_mismatch"
                    ):
                        writer.submit(request(),"0"*40)
            self.assertFalse(any(x[0]=="PATCH" for x in client.calls))

if __name__=="__main__":
    unittest.main()
