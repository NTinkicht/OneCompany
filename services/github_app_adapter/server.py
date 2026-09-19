"""Authenticated, read-only OneCompany Streamable HTTP MCP endpoint."""
from __future__ import annotations
import asyncio
import logging
from contextlib import asynccontextmanager
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from auth import BearerGuard
from github_app import AppClient, AdapterRefused
from oauth import OwnerOAuth
from settings import Settings

settings = Settings.from_environment()
client = AppClient(settings)
oauth = OwnerOAuth(settings)
host = settings.public_host if settings.host_valid() else "invalid.invalid"
security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=[host, host + ":*", "localhost:*", "127.0.0.1:*"],
    allowed_origins=[
        "https://" + host, "http://localhost:*", "http://127.0.0.1:*"
    ],
)
mcp = FastMCP(
    "OneCompany GitHub App Adapter",
    stateless_http=True, json_response=True, transport_security=security,
)

@mcp.tool()
def onecompany_actor_identity() -> dict:
    """Prove logical Grok actor and real GitHub App principal without tokens."""
    return client.identity()

@mcp.tool()
def onecompany_repository_status() -> dict:
    """Inspect only the one owner-approved repository with read-only App token."""
    return client.repository_status()

@mcp.tool()
def onecompany_pull_request_snapshot(pr_number: int, exact_head_sha: str) -> dict:
    """Inspect one PR at its exact head using the read-only bot identity."""
    return client.pull_request_snapshot(pr_number, exact_head_sha)

@mcp.tool()
def onecompany_read_source(path: str, exact_commit_sha: str,
                           start_line: int = 1, end_line: int = 160) -> dict:
    """Read 160 or fewer source lines pinned to an immutable commit."""
    return client.read_source(path, exact_commit_sha, start_line, end_line)

@mcp.tool()
def onecompany_read_document(path: str, commit_sha: str) -> dict:
    """Read allowlisted documentation from one immutable commit SHA."""
    return client.read_document(path, commit_sha)

async def health(_request: Request):
    """Unauthenticated liveness with no credential or repository metadata."""
    return JSONResponse({"status": "alive"})

async def _probe_app_identity() -> None:
    """One sanitized startup check; owner needs no extra UI action to locate 404."""
    if not settings.github_ready():
        logging.getLogger(__name__).warning(
            "OneCompany GitHub App diagnostic: not_configured_or_sealed"
        )
        return
    try:
        await asyncio.to_thread(client.identity)
    except AdapterRefused as exc:
        logging.getLogger(__name__).warning(
            "OneCompany GitHub App diagnostic: %s", exc
        )
    except Exception:
        logging.getLogger(__name__).exception(
            "OneCompany GitHub App diagnostic: unexpected_probe_failure"
        )
    else:
        logging.getLogger(__name__).info(
            "OneCompany GitHub App diagnostic: verified_read_only_identity"
        )

@asynccontextmanager
async def lifespan(_app: Starlette):
    async with mcp.session_manager.run():
        probe = asyncio.create_task(_probe_app_identity())
        try:
            yield
        finally:
            if not probe.done():
                probe.cancel()

inner = Starlette(
    routes=[
        Route("/health/live", health),
        Route("/oauth/authorize", oauth.authorize, methods=["GET", "POST"]),
        Route("/oauth/token", oauth.token, methods=["POST"]),
        Mount("/", app=mcp.streamable_http_app()),
    ],
    lifespan=lifespan,
)
app = BearerGuard(inner, settings, oauth)
