import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "local_quality_evidence.py"
spec = importlib.util.spec_from_file_location("local_quality_evidence", SCRIPT)
quality = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quality)


class LocalQualityEvidenceTests(unittest.TestCase):
    """Verify exact-revision evidence comes from the real local HTTP/UI smoke."""

    def test_non_exact_revision_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "EXACT_REVISION_REQUIRED"):
            quality.collect("main")

    def test_real_local_http_ui_quality_is_revision_bound(self):
        revision = "c" * 40
        evidence = quality.collect(revision)
        self.assertEqual(evidence["revision"], revision)
        self.assertEqual(evidence["status"], "PASS")
        self.assertEqual(evidence["scope"], "real_local_http_ui")
        self.assertFalse(evidence["deployable"])
        self.assertEqual(evidence["test"], ".onecompany/selftest/test_vertical_slice.py")


if __name__ == "__main__":
    unittest.main()
