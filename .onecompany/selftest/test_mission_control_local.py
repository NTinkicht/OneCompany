"""Mission Control must be useful, accessible and strictly read-only."""
import importlib.util
import json
import tempfile
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
    """Verify an honest evidence-first local dashboard and safe HTTP headers."""

    def test_page_escapes_projection_and_states_no_authority(self):
        """Untrusted projection fields must never be evaluated as markup."""
        page = mission.render({
            "project": {"name": "<script>alert(2)</script>"},
            "revision": "<script>alert(1)</script>",
            "readiness": "BLOCKED",
            "stage": "<img src=x onerror=alert(3)>",
            "quality": "<script>run()</script>",
            "next_action": "<script>hack()</script>",
            "blockers": ["<img src=x onerror=alert(4)>"],
            "steps": [{"title": "<script>x</script>", "status": "unknown"}],
        }).decode()
        self.assertIn("NOT READY", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertNotIn("<script>", page)
        self.assertNotIn("onerror=alert(4)>", page)
        self.assertIn("No execution or deployment authority", page)
        self.assertIn("Projection fields are unverified input", page)

    def test_evidence_first_guided_stage_and_only_local_preview(self):
        """Useful projected information is visible but never treated as authority."""
        data = {
            "project": {"name": "Example Checklist"},
            "revision": "a" * 40,
            "readiness": "READY_FOR_OWNER_PREVIEW",
            "stage": "PROPOSAL_READY_NOT_APPROVED",
            "quality": {"status": "PASS"},
            "browser": {"status": "PENDING"},
            "ci": {"status": "SUCCESS"},
            "review": {"status": "UNKNOWN"},
            "preview_url": "http://127.0.0.1:8765/",
            "blockers": ["Owner must authorize canonical Work Unit"],
            "next_action": "Verify exact-head independent review",
            "steps": [{"title": "Edit Product Brief", "status": "complete_draft_not_approved"}],
        }
        page = mission.render(data).decode()
        self.assertIn("id='status'>READY</p>", page)
        self.assertIn("Example Checklist", page)
        self.assertIn("PROPOSAL_READY_NOT_APPROVED", page)
        self.assertIn("PASS (unverified projection)", page)
        self.assertIn("PENDING (reported; not independently verified here)", page)
        self.assertIn("http://127.0.0.1:8765/", page)
        self.assertIn("Owner must authorize canonical Work Unit", page)
        self.assertIn("Edit Product Brief", page)
        self.assertIn("Verify exact-head independent review", page)

    def test_remote_credentialed_or_nonlocal_preview_never_rendered(self):
        """Dashboard must not expose or offer untrusted remote destination URLs."""
        for value in [
            "https://evil.example/secret",
            "http://user:password@127.0.0.1:8765/",
            "http://127.0.0.1:8765/?token=secret",
            "http://127.0.0.1:8765/redirect",
            "http://192.168.1.9:8765/",
            "http://localhost:99999/",
        ]:
            with self.subTest(value=value):
                page = mission.render({"preview_url": value}).decode()
                self.assertIn("UNAVAILABLE", page)
                self.assertNotIn("evil.example", page)
                self.assertNotIn("password@", page)
                self.assertNotIn("token=secret", page)
                self.assertNotIn("192.168.1.9", page)
                self.assertNotIn("localhost:99999", page)

    def test_missing_fields_are_unknown_not_verified_success(self):
        """No evidence and no approval are never silently inferred."""
        page = mission.render({"readiness": "READY_FOR_OWNER_PREVIEW"}).decode()
        self.assertEqual(page.count("UNKNOWN (no confirmed evidence)"), 5)
        self.assertIn("No blockers supplied; this does not prove clear gates", page)
        self.assertIn("Nothing here approves a Work Unit", page)
        with self.assertRaisesRegex(ValueError, "OBJECT_REQUIRED"):
            mission.render([])

    def test_real_loopback_http_page_security_headers_and_404(self):
        """Exercise HTTP serving, Host guard and no-store protection."""
        server = mission.serve({
            "revision": "a" * 40,
            "readiness": "READY_FOR_OWNER_PREVIEW",
        }, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.assertEqual(server.server_address[0], "127.0.0.1")
            base = f"http://127.0.0.1:{server.server_port}"
            with urllib.request.urlopen(base + "/", timeout=2) as response:
                page = response.read().decode()
                self.assertEqual(response.status, 200)
                self.assertIn("id='status'>READY</p>", page)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                self.assertIn("default-src 'none'",
                              response.headers["Content-Security-Policy"])
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(base + "/mutate", timeout=2)
            self.assertEqual(caught.exception.code, 404)
            forged = urllib.request.Request(base + "/", headers={
                "Host": "evil.example",
            })
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(forged, timeout=2)
            self.assertEqual(caught.exception.code, 403)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_bounded_projection_input_refused(self):
        """Reading a huge or non-object projection never starts a server."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "projection.json"
            path.write_text("x" * (mission.MAX_PROJECTION_BYTES + 1))
            self.assertEqual(mission.main(["--input", str(path), "--port", "0"]), 2)
            path.write_text(json.dumps([]))
            self.assertEqual(mission.main(["--input", str(path), "--port", "0"]), 2)


if __name__ == "__main__":
    unittest.main()
