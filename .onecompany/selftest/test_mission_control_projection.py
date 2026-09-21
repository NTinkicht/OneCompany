import importlib.util
import unittest
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


if __name__ == "__main__":
    unittest.main()
