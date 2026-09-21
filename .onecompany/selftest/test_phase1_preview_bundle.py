import importlib.util
import threading
import unittest
from pathlib import Path

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


class Phase1PreviewBundleTests(unittest.TestCase):
    """Verify combined evidence stays local, exact-revision, and non-authoritative."""

    @unittest.skipUnless(APP_PATH.is_file(), "source-only disposable demo not installed")
    def test_real_local_bundle_is_exact_revision_and_non_deployable(self):
        """Exercise the real localhost app and existing quality smoke together."""
        server, store = app.start_server(0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            revision = "d" * 40
            evidence = bundle.collect(revision, f"http://127.0.0.1:{server.server_port}/")
            self.assertEqual(evidence["revision"], revision)
            self.assertEqual(evidence["preview"]["revision"], revision)
            self.assertEqual(evidence["quality"]["revision"], revision)
            self.assertFalse(evidence["deployable"])
            self.assertFalse(evidence["authority_granted"])
        finally:
            server.shutdown()
            server.server_close()
            store.close()
            thread.join(timeout=2)

    def test_remote_preview_fails_closed_before_quality(self):
        """Reject remote targets instead of producing partial trusted evidence."""
        with self.assertRaises(ValueError):
            bundle.collect("d" * 40, "https://example.com:443/")


if __name__ == "__main__":
    unittest.main()
