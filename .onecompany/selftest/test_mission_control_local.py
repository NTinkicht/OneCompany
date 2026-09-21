import importlib.util
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "mission_control_local.py"
spec = importlib.util.spec_from_file_location("mission_control_local", SCRIPT)
mission = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mission)


class MissionControlLocalTests(unittest.TestCase):
    """Verify the Phase-1 status page is local, read-only and safely rendered."""

    def test_page_escapes_projection_and_states_no_authority(self):
        """Never interpret projection fields as markup or imply authority."""
        page = mission.render({"revision": "<script>alert(1)</script>", "ready": False}).decode()
        self.assertIn("NOT READY", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("<script>", page)
        self.assertIn("No execution or deployment authority", page)

    def test_real_loopback_http_page_and_404(self):
        """Exercise the actual loopback HTTP surface without remote binding."""
        server = mission.serve({"revision": "a" * 40, "ready": True}, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.assertEqual(server.server_address[0], "127.0.0.1")
            base = f"http://127.0.0.1:{server.server_port}"
            with urllib.request.urlopen(base + "/", timeout=2) as response:
                page = response.read().decode()
                self.assertEqual(response.status, 200)
                self.assertIn("READY", page)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(base + "/mutate", timeout=2)
            self.assertEqual(caught.exception.code, 404)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
