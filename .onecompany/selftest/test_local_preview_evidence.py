import http.server
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


preview = load(ROOT / "scripts/local_preview_evidence.py", "preview_evidence")
app = load(APP_PATH, "vertical_slice_app") if APP_PATH.is_file() else None


class _RedirectHandler(http.server.BaseHTTPRequestHandler):
    """Local fixture that attempts to redirect the preview health probe."""

    def do_GET(self):
        """Return a redirect that must never be followed by the collector."""
        self.send_response(302)
        self.send_header("Location", "https://example.com/")
        self.end_headers()

    def log_message(self, format, *args):
        """Keep the self-test quiet."""
        return


class PreviewEvidenceTests(unittest.TestCase):
    def test_remote_and_non_exact_targets_fail_closed(self):
        for url in ("https://example.com:443/", "http://10.0.0.2:8000/", "http://user@localhost:8000/"):
            with self.assertRaises(ValueError):
                preview.validate_local_url(url)
        with self.assertRaisesRegex(ValueError, "EXACT_REVISION_REQUIRED"):
            preview.collect("main", "http://127.0.0.1:8765/")

    @unittest.skipUnless(APP_PATH.is_file(), "source-only disposable demo not installed")
    def test_real_health_is_bound_to_exact_revision(self):
        server, store = app.start_server(0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            sha = "a" * 40
            evidence = preview.collect(sha, f"http://127.0.0.1:{server.server_port}/")
            self.assertEqual(evidence["revision"], sha)
            self.assertEqual(evidence["health"], "PASS")
            self.assertFalse(evidence["deployable"])
        finally:
            server.shutdown()
            server.server_close()
            store.close()
            thread.join(timeout=2)

    def test_local_health_redirect_is_rejected(self):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _RedirectHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with self.assertRaisesRegex(ValueError, "LOCAL_PREVIEW_HEALTH_FAILED"):
                preview.collect("a" * 40, f"http://127.0.0.1:{server.server_port}/")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
