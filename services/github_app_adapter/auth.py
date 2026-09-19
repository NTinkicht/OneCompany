"""Authenticate every MCP request before SDK tool discovery or execution."""
from __future__ import annotations
import hmac
from starlette.responses import PlainTextResponse
from settings import Settings

class BearerGuard:
    """The only public endpoint is a content-free health check."""
    def __init__(self, app, settings: Settings):
        self.app = app
        self.settings = settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") == "/health/live":
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
        if scheme.lower() != "bearer" or not hmac.compare_digest(
            supplied.encode("utf-8"), self.settings.connector_secret.encode("utf-8")
        ):
            await PlainTextResponse("unauthorized", status_code=401)(
                scope, receive, send
            )
            return
        await self.app(scope, receive, send)
