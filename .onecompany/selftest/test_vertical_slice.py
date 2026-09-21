from __future__ import annotations

import http.client
import json
import subprocess
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "examples" / "vertical-slice"
sys.path.insert(0, str(DEMO))
if (DEMO / "vertical_app.py").is_file():
    from vertical_app import VerticalServer  # noqa: E402
else:
    VerticalServer = None  # source-only demo does not ship with installed customer framework


@unittest.skipUnless(VerticalServer is not None, "source-only vertical demo absent from customer installation")
class VerticalSliceHTTPTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = VerticalServer(port=0)
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        )
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.assertFalse(self.thread.is_alive(), "local HTTP server failed clean shutdown")
        self.server.server_close()

    def request(self, method: str, path: str, body=None, *, raw=None,
                content_type="application/json", host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        payload = (json.dumps(body).encode("utf-8") if body is not None else raw)
        headers = {
            "Host": host or f"127.0.0.1:{self.server.server_port}",
        }
        if payload is not None:
            headers["Content-Type"] = content_type
            headers["Content-Length"] = str(len(payload))
        conn.request(method, path, body=payload, headers=headers)
        res = conn.getresponse()
        data = res.read()
        outcome = (
            res.status,
            json.loads(data.decode("utf-8"))
            if data and res.getheader("Content-Type", "").startswith("application/json")
            else data,
            dict(res.getheaders()),
        )
        conn.close()
        return outcome

    def test_real_http_health_and_browser_assets(self):
        code, obj, headers = self.request("GET", "/healthz")
        self.assertEqual(code, 200)
        self.assertEqual(obj["scope"], "local_demo_only")
        self.assertEqual(headers["Cache-Control"], "no-store")
        html_code, html, _ = self.request("GET", "/")
        self.assertEqual(html_code, 200)
        self.assertIn(b"Local task demo", html)
        js_code, js, _ = self.request("GET", "/app.js")
        self.assertEqual(js_code, 200)
        self.assertIn(b"label.textContent", js)
        self.assertNotIn(b"innerHTML", js)

    def test_create_read_update_delete_and_persistence_during_run(self):
        self.assertEqual(self.request("GET", "/api/items")[1], {"items": []})
        status, item, _ = self.request("POST", "/api/items", {"title": "  first task  "})
        self.assertEqual(status, 201)
        self.assertEqual(item["title"], "first task")
        self.assertFalse(item["done"])
        uri = f"/api/items/{item['id']}"
        self.assertEqual(self.request("GET", uri)[1], item)
        self.assertEqual(self.request("GET", "/api/items")[1]["items"], [item])
        updated = self.request("PATCH", uri, {"done": True, "title": "finished"})
        self.assertEqual(updated[0], 200)
        self.assertEqual(updated[1]["title"], "finished")
        self.assertTrue(updated[1]["done"])
        self.assertEqual(self.request("DELETE", uri)[0], 204)
        self.assertEqual(self.request("GET", uri)[0], 404)
        self.assertEqual(self.request("DELETE", uri)[0], 404)

    def test_strict_validation_and_unknown_routes(self):
        for body in ({}, {"title": " "}, {"title": "a" * 121},
                     {"title": "bad\nvalue"}, {"title": 1},
                     {"title": "okay", "admin": True}, [], "hi"):
            with self.subTest(body=body):
                self.assertEqual(self.request("POST", "/api/items", body)[0], 400)
        for raw, content_type in [
            (b"{", "application/json"),
            (b'{"title":"x"}', "text/plain"),
            (b"x" * 2049, "application/json"),
        ]:
            self.assertEqual(
                self.request("POST", "/api/items", raw=raw, content_type=content_type)[0], 400
            )
        self.assertEqual(self.request("GET", "/../../etc/passwd")[0], 404)
        self.assertEqual(self.request("GET", "/api/items?all=true")[0], 404)
        self.assertEqual(self.request("PUT", "/api/items")[0], 405)
        self.assertEqual(self.request("OPTIONS", "/api/items")[0], 405)
        self.assertEqual(self.request("GET", "/", host="evil.test")[0], 400)
        self.assertEqual(self.request("GET", "/api/items/0001")[0], 404)
        self.assertEqual(self.request("GET", "/api/items/2147483648")[0], 404)

    def test_xss_payload_remains_literal_data_and_bad_patch_does_not_change_item(self):
        markup = "<img src=x onerror=alert(1)>"
        code, item, _ = self.request("POST", "/api/items", {"title": markup})
        self.assertEqual(code, 201)
        self.assertEqual(item["title"], markup)
        uri = f"/api/items/{item['id']}"
        for patch in ({}, {"done": 1}, {"done": "true"}, {"title": ""},
                      {"title": "x", "role": "admin"}):
            self.assertEqual(self.request("PATCH", uri, patch)[0], 400)
        self.assertEqual(self.request("GET", uri)[1], item)

    def test_reject_public_network_bind_and_compile_cli(self):
        with self.assertRaises(ValueError):
            VerticalServer(host="0.0.0.0", port=0)
        cli = subprocess.run(
            [sys.executable, str(DEMO / "vertical_app.py"), "--help"],
            cwd=ROOT, capture_output=True, text=True, check=False, timeout=5,
        )
        self.assertEqual(cli.returncode, 0)
        self.assertIn("loopback", cli.stdout.lower() + cli.stderr.lower())


if __name__ == "__main__":
    unittest.main()
