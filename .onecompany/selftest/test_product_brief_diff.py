import importlib.util, json, tempfile, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("product_brief_diff", ROOT / "scripts" / "product_brief_diff.py")
MOD = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(MOD)

def brief():
    return {"schema_version":"1.0","document_kind":"product_brief_draft","status":"DRAFT_NOT_APPROVED","answers":{"audience":"Parents","problem":"Delay","outcome":"Clarity","first_feature":"Status","constraints":None},"approval":{"product_brief":False,"implementation":False,"deployment":False},"write_lease_granted":False}

class ProductBriefDiffTests(unittest.TestCase):
    def write(self, folder, name, payload):
        p=folder/name; p.write_text(json.dumps(payload),encoding="utf-8"); return p
    def test_reports_only_changed_owner_fields_without_authority(self):
        before=brief(); after=brief(); after["answers"]["outcome"]="Faster clarity"
        result=MOD.compare(before,after)
        self.assertEqual([c["field"] for c in result["changed_fields"]],["outcome"])
        self.assertFalse(result["implementation_authorized"])
        self.assertEqual(result["status"],"PREVIEW_ONLY_NOT_APPROVED")
    def test_identical_drafts_have_no_changes(self):
        self.assertEqual(MOD.compare(brief(),brief())["changed_fields"],[])
    def test_authority_bearing_input_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td); payload=brief(); payload["write_lease_granted"]=True
            with self.assertRaisesRegex(ValueError,"authority"):
                MOD.load(self.write(folder,"brief.json",payload))
    def test_symlink_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td); target=self.write(folder,"brief.json",brief()); link=folder/"link.json"; link.symlink_to(target)
            with self.assertRaisesRegex(ValueError,"symlink"):
                MOD.load(link)
if __name__ == "__main__": unittest.main()
