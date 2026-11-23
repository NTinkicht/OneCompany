import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("mission_control", ROOT / "scripts/mission_control_projection.py")
mission = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mission)


class MissionControlProjectionTests(unittest.TestCase):
    def setUp(self):
        self.sha = "b" * 40
        self.brief = {"status": "DRAFT", "approved": False}
        self.execution = {"bounded": True}
        self.evidence = {name: {"revision": self.sha, "status": "PASS"}
                         for name in ("app", "quality", "preview")}

    def test_ready_projection_never_grants_authority(self):
        result = mission.project(self.sha, self.brief, self.execution, self.evidence)
        self.assertEqual(result["readiness"], "READY_FOR_OWNER_PREVIEW")
        self.assertEqual(result["product_brief"], "DRAFT_UNAPPROVED")
        self.assertFalse(result["authority_granted"])

    def test_stale_or_missing_evidence_blocks(self):
        self.evidence["quality"]["revision"] = "c" * 40
        result = mission.project(self.sha, self.brief, self.execution, self.evidence)
        self.assertEqual(result["readiness"], "BLOCKED")
        self.assertFalse(result["checks"]["quality"]["exact_revision"])
        del self.evidence["preview"]
        result = mission.project(self.sha, self.brief, self.execution, self.evidence)
        self.assertEqual(result["checks"]["preview"]["status"], "BLOCKED")

    def test_brief_cannot_be_promoted_by_projection(self):
        with self.assertRaisesRegex(ValueError, "PRODUCT_BRIEF_MUST_REMAIN_UNAPPROVED"):
            mission.project(self.sha, {"status": "DRAFT", "approved": True}, self.execution, self.evidence)
        with self.assertRaisesRegex(ValueError, "DRAFT_PRODUCT_BRIEF_REQUIRED"):
            mission.project(self.sha, {"status": "APPROVED", "approved": False}, self.execution, self.evidence)


    def run_main(self, text: str):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "in.json"
            path.write_text(text, encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            argv = ["x", "--revision", self.sha, "--input", str(path)]
            with mock.patch("sys.argv", argv), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = mission.main()
            return code, out.getvalue(), err.getvalue()

    def test_input_with_duplicate_keys_is_refused(self):
        evidence = {name: {"revision": self.sha, "status": "PASS"} for name in ("app", "quality", "preview")}
        good = json.dumps({"product_brief": self.brief, "execution": self.execution, "evidence": evidence})
        code, out, _ = self.run_main(good)
        self.assertEqual(code, 0)
        self.assertIn("READY_FOR_OWNER_PREVIEW", out)
        forged = good.replace('"status": "PASS"', '"status": "FAIL", "status": "PASS"', 1)
        code, out, err = self.run_main(forged)
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("duplicate key", err)


if __name__ == "__main__":
    unittest.main()
