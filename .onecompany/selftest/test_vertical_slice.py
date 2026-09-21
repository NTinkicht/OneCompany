"""Real local HTTP smoke for OneCompany's disposable application vertical slice."""
from __future__ import annotations

import http.client
import importlib.util
import json
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP_PATH = ROOT / "examples" / "vertical-slice" / "app.py"
# Bootstrap installs governance/tests into customer repos but deliberately
# excludes this source-only disposable demo. Skip ONLY when it is absent;
# exercise real HTTP endpoints when running in the OneCompany source tree.
if APP_PATH.is_file():
    SPEC = importlib.util.spec_from_file_location("onecompany_local_app", APP_PATH)
    assert SPEC and SPEC.loader
    app = importlib.util.module_from_spec(SPEC)
    sys.modules[SPEC.name] = app
    SPEC.loader.exec_module(app)


@unittest.skipUnless(APP_PATH.is_file(), "source-only disposable demo not installed")
class LocalVerticalSliceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server, cls.store = app.start_server(0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        cls.store.close()

    def setUp(self) -> None:
        # Each test gets a disposable database while the actual HTTP server
        # continues running. Existing items are removed via public REST.
        status, result, _ = self.request("GET", "/api/items")
        self.assertEqual(status, 200)
        for item in result["items"]:
            self.request("DELETE", "/api/items/" + str(item["id"]),
                         headers={"X-OneCompany-Local": "1"})

    def request(self, method: str, path: str, body=None, *, headers=None):
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.server.server_port, timeout=5
        )
        request_headers = dict(headers or {})
        if body is not None and not isinstance(body, (bytes, str)):
            body = json.dumps(body)
        if body is not None and "Content-Type" not in request_headers:
            request_headers["Content-Type"] = "application/json"
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        data = response.read()
        captured = dict(response.getheaders())
        status = response.status
        connection.close()
        if captured["Content-Type"].startswith("application/json"):
            return status, json.loads(data), captured
        return status, data.decode("utf-8"), captured

    def test_actual_crud_round_trip_over_http(self):
        status, health, headers = self.request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["scope"], "local_disposable")
        self.assertEqual(headers["Cache-Control"], "no-store")
        status, item, _ = self.request("POST", "/api/items",
             {"title": "Learn OneCompany"},
             headers={"X-OneCompany-Local": "1"})
        self.assertEqual(status, 201)
        self.assertIs(type(item["id"]), int)
        self.assertFalse(item["done"])
        status, state, _ = self.request("GET", "/api/items")
        self.assertEqual(status, 200)
        self.assertEqual([row["title"] for row in state["items"]],
                         ["Learn OneCompany"])
        status, result, _ = self.request("PATCH", f"/api/items/{item['id']}",
            {"done": True}, headers={"X-OneCompany-Local": "1"})
        self.assertEqual((status, result), (200, {"ok": True}))
        status, state, _ = self.request("GET", "/api/items")
        self.assertTrue(state["items"][0]["done"])
        status, result, _ = self.request("DELETE", f"/api/items/{item['id']}",
             headers={"X-OneCompany-Local": "1"})
        self.assertEqual((status, result), (200, {"ok": True}))
        status, state, _ = self.request("GET", "/api/items")
        self.assertEqual(state, {"items": []})
        status, _, _ = self.request("DELETE", f"/api/items/{item['id']}",
             headers={"X-OneCompany-Local": "1"})
        self.assertEqual(status, 404)

    def test_real_ui_assets_and_dom_safe_rendering(self):
        status, html, headers = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn('id="items"', html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn("default-src 'none'", headers["Content-Security-Policy"])
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        status, javascript, _ = self.request("GET", "/app.js")
        self.assertEqual(status, 200)
        self.assertIn("text.textContent=item.title", javascript)
        self.assertNotIn("innerHTML", javascript)
        status, css, _ = self.request("GET", "/app.css")
        self.assertEqual(status, 200)
        self.assertIn("focus-visible", css)
        self.assertEqual(self.server.server_address[0], "127.0.0.1")

    def test_mutations_require_same_origin_and_non_simple_header(self):
        for headers in (
            {},
            {"X-OneCompany-Local": "1",
             "Origin": "https://evil.example"},
            {"X-OneCompany-Local": "1",
             "Origin": "http://localhost.evil.example"},
        ):
            with self.subTest(headers=headers):
                status, _, _ = self.request(
                    "POST", "/api/items", {"title": "should not exist"},
                    headers=headers,
                )
                self.assertEqual(status, 403)
        status, state, _ = self.request("GET", "/api/items")
        self.assertEqual(state["items"], [])

    def test_malformed_and_oversized_body_fail_closed(self):
        for payload, expected in (
            ({"title": ""}, 400),
            ({"title": "A" * 121}, 400),
            ({"title": "bad\nnewline"}, 400),
            ({"title": 2}, 400),
            ({"title": "ok", "owner": True}, 400),
            (b"{bad json", 400),
            (b" " * 4097, 413),
        ):
            with self.subTest(payload=str(payload)[:45]):
                status, _, _ = self.request(
                    "POST", "/api/items", payload,
                    headers={"X-OneCompany-Local": "1"},
                )
                self.assertEqual(status, expected)
        status, item, _ = self.request(
            "POST", "/api/items", {"title": "valid"},
            headers={"X-OneCompany-Local": "1"},
        )
        self.assertEqual(status, 201)
        for payload in ({"done": 1}, {"done": "true"},
                        {"done": True, "other": False}, []):
            with self.subTest(payload=payload):
                status, _, _ = self.request(
                    "PATCH", f"/api/items/{item['id']}", payload,
                    headers={"X-OneCompany-Local": "1"},
                )
                self.assertEqual(status, 400)

    def test_bad_ids_and_routes_are_bounded(self):
        for method, path, body in (
            ("DELETE", "/api/items/0", None),
            ("PATCH", "/api/items/abc", {"done": True}),
            ("DELETE", "/api/items/123456789012345", None),
        ):
            status, _, _ = self.request(
                method, path, body,
                headers={"X-OneCompany-Local": "1"},
            )
            self.assertEqual(status, 400)
        for path in ("/api/private", "/debug", "/favicon.ico"):
            status, _, _ = self.request("GET", path)
            self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
