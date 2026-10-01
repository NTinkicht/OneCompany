#!/usr/bin/env python3
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from l5_kernel import RepoMode
from l5_ledger import *

def base():
 return {"schema_version":1,"repository":"NTinkicht/test","revision":0,"mode":"GOVERNANCE_DRIFT","mode_version":1,"human_clear_required":True,"leases":{},"budgets":{},"observations":{},"platform_enforcement":{"branch_protected":False,"active_rulesets":0}}
class LedgerTests(unittest.TestCase):
 def test_valid_fail_closed_ledger(self):validate_ledger(base(),expected_repo="NTinkicht/test")
 def test_blob_sha_is_storage_cas(self):self.assertTrue(blob_cas_ok("abc","abc"));self.assertFalse(blob_cas_ok("abc","def"))
 def test_stale_document_revision_rejected(self):
  with self.assertRaises(LedgerConflict):cas_lease(base(),"k",expected_revision=1,expected_lease_version=None,new_record={"version":1})
 def test_lease_versions_monotonic(self):
  d=cas_lease(base(),"k",expected_revision=0,expected_lease_version=None,new_record={"version":1})
  with self.assertRaises(LedgerInvalid):cas_lease(d,"k",expected_revision=1,expected_lease_version=1,new_record={"version":1})
 def test_integrity_freeze_requires_human_clear(self):
  with self.assertRaises(LedgerConflict):cas_mode(base(),expected_revision=0,expected_mode_version=1,new_mode=RepoMode.NORMAL)
  d=cas_mode(base(),expected_revision=0,expected_mode_version=1,new_mode=RepoMode.NORMAL,human_clear=True);self.assertEqual(d["mode"],"NORMAL")
if __name__=="__main__":unittest.main()
