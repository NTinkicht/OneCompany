"""Offline OAuth/PKCE bridge tests with real ASGI HTTP request handling."""
from __future__ import annotations
import asyncio
import hashlib
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from auth import BearerGuard
from oauth import CLIENT_ID, OwnerOAuth, SCOPE, _b64
from settings import Settings

CALLBACK = "https://grok.com/connectors-oauth-exchange-code/"
VERIFIER = "v" * 50
CHALLENGE = _b64(hashlib.sha256(VERIFIER.encode()).digest())
SECRET = "S" * 48

def oauth_args():
    return {
        "client_id": CLIENT_ID,
        "redirect_uri": CALLBACK,
        "response_type": "code",
        "scope": SCOPE,
        "state": "grok-state-123",
        "code_challenge": CHALLENGE,
        "code_challenge_method": "S256",
    }

class TestGrokOAuth(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        s = Settings(True, SECRET, 12, 34, Path("/nonexistent"),
                     "NTinkicht/OneCompany",
                     "onecompany-github-adapter.onrender.com")
        self.oauth = OwnerOAuth(s)
        async def protected(_request):
            return JSONResponse({"approved": True})
        inner = Starlette(routes=[
            Route("/oauth/authorize", self.oauth.authorize,
                  methods=["GET", "POST"]),
            Route("/oauth/token", self.oauth.token, methods=["POST"]),
            Route("/mcp", protected, methods=["GET"]),
        ])
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(
                app=BearerGuard(inner, s, self.oauth)),
            base_url="https://onecompany-github-adapter.onrender.com",
            follow_redirects=False,
        )

    async def asyncTearDown(self):
        await self.client.aclose()

    async def authorize(self, args=None):
        data = oauth_args() if args is None else args
        response = await self.client.get("/oauth/authorize", params=data)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(SECRET, response.text)
        refused = await self.client.post(
            "/oauth/authorize",
            data={**data, "owner_password": "wrong"},
        )
        self.assertEqual(refused.status_code, 403)
        good = await self.client.post(
            "/oauth/authorize",
            data={**data, "owner_password": SECRET},
        )
        self.assertEqual(good.status_code, 303)
        uri = urlsplit(good.headers["location"])
        self.assertEqual(
            uri.scheme + "://" + uri.netloc + uri.path, CALLBACK
        )
        params = parse_qs(uri.query)
        self.assertEqual(params["state"], ["grok-state-123"])
        return params["code"][0]

    async def test_pkce_valid_code_refresh_and_guard(self):
        code = await self.authorize()
        body = {
            "client_id": CLIENT_ID,
            "grant_type": "authorization_code",
            "redirect_uri": CALLBACK,
            "code": code,
            "code_verifier": VERIFIER,
        }
        self.assertEqual((await self.client.get("/mcp")).status_code, 401)
        token_response = await self.client.post("/oauth/token", data=body)
        self.assertEqual(token_response.status_code, 200)
        self.assertEqual(token_response.headers["cache-control"], "no-store")
        tokens = token_response.json()
        self.assertNotEqual(tokens["access_token"], SECRET)
        self.assertTrue(self.oauth.valid_token(tokens["access_token"]))
        ok = await self.client.get(
            "/mcp",
            headers={"Authorization": "Bearer " + tokens["access_token"]},
        )
        self.assertEqual(ok.json(), {"approved": True})
        self.assertEqual(
            (await self.client.post("/oauth/token", data=body)).status_code, 400
        )
        refreshed = await self.client.post(
            "/oauth/token",
            data={"client_id": CLIENT_ID, "grant_type": "refresh_token",
                  "refresh_token": tokens["refresh_token"]},
        )
        self.assertEqual(refreshed.status_code, 200)
        self.assertTrue(self.oauth.valid_token(
            refreshed.json()["access_token"]
        ))

    async def test_refuses_foreign_redirect_and_wrong_pkce(self):
        params = oauth_args()
        params["redirect_uri"] = "https://attacker.example/callback"
        response = await self.client.get("/oauth/authorize", params=params)
        self.assertEqual(response.status_code, 400)
        code = await self.authorize()
        body = {
            "client_id": CLIENT_ID,
            "grant_type": "authorization_code",
            "redirect_uri": CALLBACK,
            "code": code,
            "code_verifier": "w" * 50,
        }
        self.assertEqual(
            (await self.client.post("/oauth/token", data=body)).status_code,
            400,
        )
        body["code_verifier"] = VERIFIER
        self.assertEqual(
            (await self.client.post("/oauth/token", data=body)).status_code,
            400,  # failed exchange consumes code; replay fails
        )

    async def test_sealed_service_refuses_oauth(self):
        self.oauth.settings = Settings(
            False, SECRET, 12, 34, Path("/nonexistent"),
            "NTinkicht/OneCompany",
            "onecompany-github-adapter.onrender.com",
        )
        self.assertEqual(
            (await self.client.get(
                "/oauth/authorize", params=oauth_args()
            )).status_code, 503
        )
        self.assertEqual(
            (await self.client.post("/oauth/token",
                                    data={"client_id": CLIENT_ID}
            )).status_code, 503
        )

if __name__ == "__main__":
    unittest.main()
