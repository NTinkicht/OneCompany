import importlib.util
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

# This self-test exercises the production clean-checkout guard. Prevent Python
# from manufacturing __pycache__ files in the checkout before that guard runs
# instead of teaching the test to hide repository status entries.
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[2]
APP_PATH = ROOT / "examples" / "vertical-slice" / "app.py"


def load(path, name):
    """Load one source-tree helper for focused self-testing."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bundle = load(ROOT / "scripts" / "phase1_preview_bundle.py", "phase1_preview_bundle")
app = load(APP_PATH, "vertical_slice_app") if APP_PATH.is_file() else None


def checkout_head():
    """Use the actual checked-out commit, not a syntactically valid placeholder."""
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout.strip()


class Phase1PreviewBundleTests(unittest.TestCase):
    """Combined evidence must be local, exact-revision, and non-authoritative."""

    @unittest.skipUnless(APP_PATH.is_file(), "source-only disposable demo not installed")
    def test_real_local_bundle_is_exact_revision_and_non_deployable(self):
        """Probe real localhost health and execute actual HTTP/UI smoke."""
        server, store = app.start_server(0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            revision = checkout_head()
            evidence = bundle.collect(
                revision, f"http://127.0.0.1:{server.server_port}/"
            )
            self.assertEqual(evidence["revision"], revision)
            self.assertEqual(evidence["preview"]["revision"], revision)
            self.assertEqual(evidence["quality"]["revision"], revision)
            self.assertEqual(evidence["preview"]["health"], "PASS")
            self.assertEqual(evidence["quality"]["status"], "PASS")
            self.assertFalse(evidence["deployable"])
            self.assertFalse(evidence["authority_granted"])
        finally:
            server.shutdown()
            server.server_close()
            store.close()
            thread.join(timeout=2)

    def test_remote_preview_fails_closed_before_quality(self):
        with patch.object(bundle.quality, "collect") as quality:
            with self.assertRaisesRegex(ValueError, "LOCAL_PREVIEW_URL_REQUIRED"):
                bundle.collect(checkout_head(), "https://example.com:443/")
            quality.assert_not_called()

    def test_revision_mismatch_refused_even_with_local_health(self):
        """A valid-looking but untrusted revision cannot borrow the real quality pass."""
        revision = checkout_head()
        wrong = "0" * 40 if revision != "0" * 40 else "1" * 40
        with patch.object(
            bundle.preview, "collect",
            return_value={"revision": revision, "health": "PASS"},
        ) as preview_collect, patch.object(
            bundle.quality, "collect",
            return_value={"revision": wrong, "status": "PASS"},
        ) as quality_collect:
            with self.assertRaisesRegex(ValueError, "EXACT_REVISION_EVIDENCE_MISMATCH"):
                bundle.collect(revision, "http://127.0.0.1:8765/")
            preview_collect.assert_called_once_with(
                revision, "http://127.0.0.1:8765/"
            )
            quality_collect.assert_called_once_with(revision)

    def test_failed_quality_refused_not_published_as_bundle(self):
        revision = checkout_head()
        with patch.object(
            bundle.preview, "collect",
            return_value={"revision": revision, "health": "PASS"},
        ), patch.object(
            bundle.quality, "collect",
            return_value={"revision": revision, "status": "FAIL"},
        ):
            with self.assertRaisesRegex(ValueError, "PHASE1_LOCAL_EVIDENCE_FAILED"):
                bundle.collect(revision, "http://127.0.0.1:8765/")


if __name__ == "__main__":
    unittest.main()
