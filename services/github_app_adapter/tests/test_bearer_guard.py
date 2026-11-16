"""OC-P0-10: BearerGuard refusal and request-scope integrity (offline ASGI)."""
from __future__ import annotations
import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from auth import BearerGuard
from settings import Settings

SECRET = "S" * 48


def make_settings(secret=SECRET, enabled=True):
    return Settings(enabled, secret, 12, 34, Path("/nonexistent"),
                    "NTinkicht/OneCompany", "adapter.example.com")


def call(settings, headers, scope_extra=None, path="/mcp"):
    reached = []
    sent = []

    async def app(scope, receive, send):
        reached.append(scope.get("onecompany.oauth_scope"))

    async def send(event):
        sent.append(event)

    scope = {"type": "http", "path": path, "headers": headers}
    scope.update(scope_extra or {})
    asyncio.run(BearerGuard(app, settings)(scope, None, send))
    status = sent[0]["status"] if sent else None
    return status, reached


def auth(value: bytes):
    return [(b"authorization", value)]


class TestBearerGuard(unittest.TestCase):
    def test_positive_control_valid_secret_reaches_app_read_only(self):
        status, reached = call(make_settings(), auth(b"Bearer " + SECRET.encode()))
        self.assertIsNone(status)
        self.assertEqual(reached, ["onecompany:read"])

    def test_non_bearer_scheme_with_correct_secret_is_refused(self):
        for value in (b"Basic " + SECRET.encode(), b"Token " + SECRET.encode(),
                      SECRET.encode()):
            with self.subTest(value=value[:6]):
                status, reached = call(make_settings(), auth(value))
                self.assertEqual(status, 401)
                self.assertEqual(reached, [])

    def test_empty_or_non_ascii_credential_is_refused(self):
        for value in (b"Bearer ", b"Bearer", b"Bearer \xff\xfe" + SECRET.encode()):
            with self.subTest(value=value):
                status, reached = call(make_settings(), auth(value))
                self.assertEqual(status, 401)
                self.assertEqual(reached, [])

    def test_secret_in_query_or_other_header_is_not_a_credential(self):
        status, reached = call(
            make_settings(),
            [(b"x-api-key", SECRET.encode())],
            {"query_string": b"access_token=" + SECRET.encode()},
        )
        self.assertEqual(status, 401)
        self.assertEqual(reached, [])

    def test_weak_or_blank_secret_keeps_adapter_sealed_even_if_matching(self):
        for secret in ("short", " " * 40, ""):
            with self.subTest(secret=secret):
                status, reached = call(
                    make_settings(secret=secret), auth(b"Bearer " + secret.encode()))
                self.assertEqual(status, 503)
                self.assertEqual(reached, [])
        status, reached = call(make_settings(), auth(b"Bearer " + SECRET.encode()))
        self.assertIsNone(status)

    def test_client_cannot_preseed_write_scope(self):
        status, reached = call(
            make_settings(), auth(b"Bearer " + SECRET.encode()),
            {"onecompany.oauth_scope": "onecompany:write"},
        )
        self.assertIsNone(status)
        self.assertEqual(reached, ["onecompany:read"])

    def test_scope_header_cannot_grant_write(self):
        status, reached = call(
            make_settings(),
            auth(b"Bearer " + SECRET.encode())
            + [(b"onecompany.oauth_scope", b"onecompany:write"),
               (b"x-onecompany-scope", b"onecompany:write")],
        )
        self.assertIsNone(status)
        self.assertEqual(reached, ["onecompany:read"])


if __name__ == "__main__":
    unittest.main()
