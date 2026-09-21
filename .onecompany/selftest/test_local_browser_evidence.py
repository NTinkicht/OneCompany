from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import local_browser_evidence as browser

SHA = "a" * 40
URL = "http://127.0.0.1:8765/"


class BrowserEvidenceGuards(unittest.TestCase):
    def test_exact_revision_required_before_browser(self):
        for candidate in ("main", "a" * 7, "Z" * 40, "", None):
            with self.subTest(candidate=candidate), self.assertRaisesRegex(ValueError, "EXACT_REVISION"):
                browser.collect(candidate, URL)

    def test_remote_or_credentialed_urls_refused_without_browser(self):
        for url in ("https://example.com/", "http://example.com:8765/",
                    "http://127.0.0.1:8765/api/items", "http://u:p@localhost:8765/",
                    "http://localhost:8765/?token=x"):
            with self.subTest(url=url), self.assertRaises(ValueError), patch.object(
                    browser.quality, "_checkout_revision", side_effect=AssertionError("should not touch git")):
                browser.collect(SHA, url)

    def test_dirty_or_wrong_checkout_refused_before_any_browser(self):
        with patch.object(browser.quality, "_checkout_revision", return_value="b" * 40), patch.object(
                browser.preview, "collect", side_effect=AssertionError("must not probe")):
            with self.assertRaisesRegex(ValueError, "REVISION_CHECKOUT_MISMATCH"):
                browser.collect(SHA, URL)

    def test_failed_local_health_refused_before_browser(self):
        with patch.object(browser.quality, "_checkout_revision", return_value=SHA), patch.object(
                browser.preview, "collect", return_value={"revision": SHA, "health": "FAIL"}):
            with self.assertRaisesRegex(ValueError, "LOCAL_PREVIEW_HEALTH_FAILED"):
                browser.collect(SHA, URL)


if __name__ == "__main__":
    unittest.main()
