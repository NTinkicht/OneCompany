"""Guard protected MCP transport while allowing owner-authorized OAuth routes."""
from __future__ import annotations
import hmac
from starlette.responses import PlainTextResponse
from oauth import OwnerOAuth
from settings import Settings

class BearerGuard:
    """No MCP tools are exposed without authenticated owner-issued credentials."""
    def __init__(self, app, settings: Settings, oauth: OwnerOAuth | None = None):
        self.app = app
        self.settings = settings
        self.oauth = oauth or OwnerOAuth(settings)

    async def __call__(self, scope, receive, send):
        path = scope.get("path")
        if (scope["type"] != "http" or path == "/health/live"
                or path in {"/oauth/authorize", "/oauth/token"}):
            await self.app(scope, receive, send)
            return
        if not self.settings.auth_ready():
            await PlainTextResponse("adapter sealed", status_code=503)(
                scope, receive, send
            )
            return
        headers = [
            value for key, value in scope.get("headers", [])
            if key.lower() == b"authorization"
        ]
        if len(headers) != 1:
            await PlainTextResponse("unauthorized", status_code=401)(
                scope, receive, send
            )
            return
        try:
            scheme, supplied = headers[0].decode("ascii").split(" ", 1)
        except (UnicodeError, ValueError):
            scheme, supplied = "", ""
        authorized = (
            scheme.lower() == "bearer"
            and (
                hmac.compare_digest(
                    supplied.encode("utf-8"),
                    self.settings.connector_secret.encode("utf-8"),
                )
                or self.oauth.valid_token(supplied)
            )
        )
        if not authorized:
            await PlainTextResponse("unauthorized", status_code=401)(
                scope, receive, send
            )
            return
        await self.app(scope, receive, send)
