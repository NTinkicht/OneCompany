"""Single-owner, read-only OAuth2 + PKCE bridge for Grok web custom connectors.

This service does NOT authenticate GitHub users. The owner unlocks the OAuth
consent once using the existing Render-side ONECOMPANY_CONNECTOR_BEARER.
All issued credentials are audience-bound HMAC tokens signed with that secret.
Rotating it immediately revokes all sessions. No GitHub key or installation
token is returned by this authorization server.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import re
import secrets
import time
from urllib.parse import parse_qs, urlencode

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from settings import Settings

CLIENT_ID = "onecompany-grok-web"
SCOPE = "onecompany:read"
_ACCESS_TTL = 3600
_REFRESH_TTL = 30 * 86400
_CODE_TTL = 300
_ALLOWED_REDIRECTS = frozenset(
    f"https://{domain}/connectors-oauth-exchange-code{slash}"
    for domain in ("grok.com", "www.grok.com")
    for slash in ("", "/")
)
_CHALLENGE = re.compile(r"^[A-Za-z0-9_-]{43,128}$")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _response(message: str, code: int) -> JSONResponse:
    return JSONResponse(
        {"error": message}, status_code=code,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


class OwnerOAuth:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.codes: dict[str, dict] = {}

    def _valid_request(self, args) -> bool:
        return (
            args.get("client_id") == CLIENT_ID
            and args.get("redirect_uri") in _ALLOWED_REDIRECTS
            and args.get("response_type") == "code"
            and args.get("scope", SCOPE) == SCOPE
            and args.get("code_challenge_method") == "S256"
            and isinstance(args.get("code_challenge"), str)
            and bool(_CHALLENGE.fullmatch(args["code_challenge"]))
            and len(args.get("state", "")) <= 512
            and len(args.get("state", "")) > 0
        )

    def _sign(self, kind: str, ttl: int) -> str:
        body = {
            "t": kind,
            "aud": "onecompany-grok-mcp",
            "exp": int(time.time()) + ttl,
            "nonce": secrets.token_urlsafe(16),
            "actor": self.settings.actor,
        }
        packed = _b64(json.dumps(body, separators=(",", ":")).encode())
        digest = _b64(hmac.digest(
            self.settings.connector_secret.encode(), packed.encode(), "sha256",
        ))
        return packed + "." + digest

    def valid_token(self, token: str, kind: str = "access") -> bool:
        if not self.settings.auth_ready() or len(token) > 4096:
            return False
        try:
            packed, sig = token.split(".", 1)
            correct = _b64(hmac.digest(
                self.settings.connector_secret.encode(), packed.encode(), "sha256",
            ))
            if not hmac.compare_digest(correct, sig):
                return False
            body = json.loads(_unb64(packed))
            return (
                isinstance(body, dict) and body.get("t") == kind
                and body.get("aud") == "onecompany-grok-mcp"
                and body.get("actor") == self.settings.actor
                and isinstance(body.get("exp"), int)
                and body["exp"] > time.time()
            )
        except (ValueError, UnicodeError, TypeError, AttributeError):
            return False

    async def _bounded_form(self, request: Request) -> dict[str, str] | None:
        """Bound the bytes ACTUALLY received, even without Content-Length."""
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/x-www-form-urlencoded":
            return None
        length = request.headers.get("content-length")
        if length is not None:
            try:
                if int(length) < 0 or int(length) > 8192:
                    return None
            except ValueError:
                return None
        payload = bytearray()
        async for chunk in request.stream():
            if len(payload) + len(chunk) > 8192:
                return None
            payload.extend(chunk)
        try:
            fields = parse_qs(
                payload.decode("utf-8"), keep_blank_values=True,
                strict_parsing=True, max_num_fields=16,
            )
        except (ValueError, UnicodeError):
            return None
        if any(len(values) != 1 for values in fields.values()):
            return None
        return {key: values[0] for key, values in fields.items()}

    async def authorize(self, request: Request):
        if not self.settings.auth_ready():
            return _response("temporarily_unavailable", 503)
        if request.method == "GET":
            if len(request.scope.get("query_string", b"")) > 8192:
                return _response("invalid_request", 400)
            args = dict(request.query_params)
        else:
            args = await self._bounded_form(request)
            if args is None:
                return _response("invalid_request", 400)
        if not self._valid_request(args):
            return _response("invalid_request", 400)
        if request.method == "GET":
            hidden = "".join(
                '<input type="hidden" name="' + html.escape(key, quote=True)
                + '" value="' + html.escape(str(value), quote=True) + '">'
                for key, value in args.items()
            )
            page = (
                "<!doctype html><html lang='en'><meta charset='utf-8'>"
                "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<title>Authorize OneCompany read-only connector</title>"
                "<main style='max-width:500px;margin:10vh auto;font:16px system-ui'>"
                "<h1>Connect Grok to OneCompany</h1>"
                "<p>Authorize READ-ONLY access to NTinkicht/OneCompany. "
                "This cannot modify branches, approve reviews or merge PRs.</p>"
                "<p>Enter the existing OneCompany connector password "
                "you saved in Render (not your GitHub private key).</p>"
                "<form method='post' action='/oauth/authorize'>"
                + hidden
                + "<label>OneCompany connector password "
                "<input type='password' name='owner_password' required "
                "autocomplete='off'></label><p><button type='submit'>"
                "Authorize read-only connector</button></p></form></main></html>"
            )
            return HTMLResponse(
                page, headers={
                    "Cache-Control": "no-store",
                    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self' https://grok.com https://www.grok.com; base-uri 'none'; frame-ancestors 'none'",
                    "Referrer-Policy": "no-referrer",
                    "X-Content-Type-Options": "nosniff",
                },
            )
        pwd = args.get("owner_password", "")
        if not hmac.compare_digest(
            pwd.encode("utf-8"), self.settings.connector_secret.encode("utf-8")
        ):
            return _response("owner_authorization_denied", 403)
        now = time.time()
        self.codes = {
            key: value for key, value in self.codes.items()
            if value["exp"] > now
        }
        code = secrets.token_urlsafe(32)
        self.codes[hashlib.sha256(code.encode()).hexdigest()] = {
            "exp": now + _CODE_TTL,
            "client_id": args["client_id"],
            "redirect_uri": args["redirect_uri"],
            "challenge": args["code_challenge"],
        }
        query = urlencode({"code": code, "state": args["state"]})
        separator = "&" if "?" in args["redirect_uri"] else "?"
        return RedirectResponse(
            args["redirect_uri"] + separator + query, status_code=303,
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )

    async def token(self, request: Request):
        if not self.settings.auth_ready():
            return _response("temporarily_unavailable", 503)
        args = await self._bounded_form(request)
        if args is None:
            return _response("invalid_request", 400)
        if args.get("client_id") != CLIENT_ID:
            return _response("invalid_client", 401)
        grant = args.get("grant_type")
        if grant == "authorization_code":
            code = args.get("code", "")
            entry = self.codes.pop(hashlib.sha256(code.encode()).hexdigest(), None)
            if not entry or entry["exp"] <= time.time():
                return _response("invalid_grant", 400)
            if args.get("redirect_uri") != entry["redirect_uri"]:
                return _response("invalid_grant", 400)
            verifier = args.get("code_verifier", "")
            if not _CHALLENGE.fullmatch(verifier):
                return _response("invalid_grant", 400)
            challenge = _b64(hashlib.sha256(verifier.encode()).digest())
            if not hmac.compare_digest(challenge, entry["challenge"]):
                return _response("invalid_grant", 400)
        elif grant == "refresh_token":
            if not self.valid_token(args.get("refresh_token", ""), "refresh"):
                return _response("invalid_grant", 400)
        else:
            return _response("unsupported_grant_type", 400)
        return JSONResponse(
            {
                "access_token": self._sign("access", _ACCESS_TTL),
                "refresh_token": self._sign("refresh", _REFRESH_TTL),
                "token_type": "Bearer",
                "expires_in": _ACCESS_TTL,
                "scope": SCOPE,
            },
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )
