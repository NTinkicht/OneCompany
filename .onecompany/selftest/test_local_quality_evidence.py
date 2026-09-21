import importlib.util
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "local_quality_evidence.py"
spec = importlib.util.spec_from_file_location("local_quality_evidence", SCRIPT)
quality = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quality)


def checkout_head():
    """Return the exact revision exercised by this checkout."""
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout.strip()


class LocalQualityEvidenceTests(unittest.TestCase):
    """Verify evidence is bound to the clean checkout running the real HTTP/UI smoke."""

    def test_non_exact_revision_fails_closed(self):
        """Reject symbolic or abbreviated revisions."""
        with self.assertRaisesRegex(ValueError, "EXACT_REVISION_REQUIRED"):
            quality.collect("main")

    def test_wrong_exact_revision_fails_closed(self):
        """Reject a syntactically exact SHA that is not the checkout under test."""
        wrong = "0" * 40 if checkout_head() != "0" * 40 else "1" * 40
        with self.assertRaisesRegex(ValueError, "REVISION_CHECKOUT_MISMATCH"):
            quality.collect(wrong)

    def test_real_local_http_ui_quality_is_revision_bound(self):
        """Bind successful evidence to the exact clean checkout HEAD."""
        revision = checkout_head()
        evidence = quality.collect(revision)
        self.assertEqual(evidence["revision"], revision)
        self.assertEqual(evidence["status"], "PASS")
        self.assertEqual(evidence["scope"], "real_local_http_ui")
        self.assertFalse(evidence["deployable"])
        self.assertEqual(evidence["test"], ".onecompany/selftest/test_vertical_slice.py")


if __name__ == "__main__":
    unittest.main()
