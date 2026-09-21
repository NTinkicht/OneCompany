import importlib.util
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

preview = load(ROOT / "scripts/local_preview_evidence.py", "preview_evidence")
app = load(ROOT / "examples/vertical-slice/app.py", "vertical_slice_app")


class PreviewEvidenceTests(unittest.TestCase):
    def test_remote_and_non_exact_targets_fail_closed(self):
        for url in ("https://example.com:443/", "http://10.0.0.2:8000/", "http://user@localhost:8000/"):
            with self.assertRaises(ValueError):
                preview.validate_local_url(url)
        with self.assertRaisesRegex(ValueError, "EXACT_REVISION_REQUIRED"):
            preview.collect("main", "http://127.0.0.1:8765/")

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


if __name__ == "__main__":
    unittest.main()
