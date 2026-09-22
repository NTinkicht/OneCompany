"""Integration coverage for the canonical Mission Control projection/view contract."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
PROJECTION_PATH = ROOT / "scripts" / "mission_control_projection.py"
VIEW_PATH = ROOT / "scripts" / "mission_control_local.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Bootstrap intentionally installs reusable governance/tests without source-only
# product helpers. Keep installed-target validation green while exercising the
# real adapter contract in the OneCompany source tree where both helpers exist.
SOURCE_HELPERS_PRESENT = PROJECTION_PATH.is_file() and VIEW_PATH.is_file()
if SOURCE_HELPERS_PRESENT:
    projection = _load("mission_control_projection", PROJECTION_PATH)
    view = _load("mission_control_local", VIEW_PATH)
else:
    projection = None
    view = None


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
        self.assertIn("Browser</strong>: PASS (unverified projection)", page)
        self.assertNotIn("Quality</strong>: UNKNOWN", page)
        self.assertNotIn("Browser</strong>: UNKNOWN", page)
        self.assertIn("CI</strong>: UNKNOWN", page)
        self.assertIn("Review</strong>: UNKNOWN", page)
        self.assertIn("READY_FOR_OWNER_PREVIEW", page)


if __name__ == "__main__":
    unittest.main()
