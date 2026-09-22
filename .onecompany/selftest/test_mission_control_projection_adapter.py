"""Integration coverage for the canonical Mission Control projection/view contract."""
import importlib.util
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
PROJECTION_PATH = ROOT / "scripts" / "mission_control_projection.py"
VIEW_PATH = ROOT / "scripts" / "mission_control_local.py"
JOURNEY_PATH = ROOT / "scripts" / "first_run_journey.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Bootstrap intentionally installs reusable governance/tests without source-only
# product helpers. Keep installed-target validation green while exercising the
# real adapter contract in the OneCompany source tree where both helpers exist.
SOURCE_HELPERS_PRESENT = PROJECTION_PATH.is_file() and VIEW_PATH.is_file() and JOURNEY_PATH.is_file()
if SOURCE_HELPERS_PRESENT:
    projection = _load("mission_control_projection", PROJECTION_PATH)
    view = _load("mission_control_local", VIEW_PATH)
    sys.path.insert(0, str(ROOT / "scripts"))
    journey_module = _load("first_run_journey", JOURNEY_PATH)
else:
    projection = None
    view = None
    journey_module = None


@unittest.skipUnless(SOURCE_HELPERS_PRESENT, "source-only Mission Control helpers not installed")
class MissionControlProjectionAdapterTests(unittest.TestCase):
    def test_canonical_exact_head_quality_and_preview_do_not_become_unknown(self):
        revision = "a" * 40
        result = projection.project(
            revision,
            {"status": "DRAFT", "approved": False},
            {"bounded": True},
            {
                "app": {"revision": revision, "status": "PASS"},
                "quality": {"revision": revision, "status": "PASS"},
                "preview": {"revision": revision, "status": "PASS"},
            },
        )
        page = view.render(result).decode()
        self.assertIn("Quality</strong>: PASS (unverified projection)", page)
        self.assertIn("Preview</strong>: PASS (unverified projection)", page)
        self.assertIn("Browser</strong>: UNKNOWN", page)
        self.assertNotIn("Quality</strong>: UNKNOWN", page)
        self.assertNotIn("Preview</strong>: UNKNOWN", page)
        self.assertIn("CI</strong>: UNKNOWN", page)
        self.assertIn("Review</strong>: UNKNOWN", page)
        self.assertIn("READY_FOR_OWNER_PREVIEW", page)

    def test_actual_first_run_producer_composes_without_granting_authority(self):
        revision = "a" * 40
        result = projection.project(
            revision, {"status": "DRAFT", "approved": False},
            {"bounded": True},
            {key: {"revision": revision, "status": "PASS"}
             for key in ("app", "quality", "preview")},
        )
        assessment = {
            "journey": {"path": "create", "steps": [
                {"id": "brief", "title": "Edit Product Brief", "status": "pending"}]},
            "blockers": [], "target": "/tmp/disposable-demo",
            "repository": "NTinkicht/disposable-demo",
            "project_name": "Disposable demo", "default_branch": "main",
            "stack": [], "tests": [], "ci": [], "contracts": {},
        }
        journey = journey_module.view(assessment)
        dashboard = view.combine_projection_journey(result, journey)
        page = view.render(dashboard).decode()
        self.assertIn("Disposable demo", page)
        self.assertIn("Edit Product Brief: needs_input", page)
        self.assertIn("Quality</strong>: PASS (unverified projection)", page)
        self.assertIn("Preview</strong>: PASS (unverified projection)", page)
        self.assertIn("Browser</strong>: UNKNOWN", page)
        self.assertIn("CI</strong>: UNKNOWN", page)
        self.assertIs(dashboard["authority_granted"], False)
        self.assertEqual(dashboard["revision"], revision)
        self.assertEqual(dashboard["schema"], "onecompany.mission-control-dashboard.phase1.v1")
        with self.assertRaisesRegex(ValueError, "CANONICAL_READ_ONLY_JOURNEY_REQUIRED"):
            view.combine_projection_journey(result, dict(journey, approval="GRANTED"))
        with self.assertRaisesRegex(ValueError, "CANONICAL_UNAUTHORIZED_PROJECTION_REQUIRED"):
            view.combine_projection_journey(dict(result, authority_granted=True), journey)


if __name__ == "__main__":
    unittest.main()
