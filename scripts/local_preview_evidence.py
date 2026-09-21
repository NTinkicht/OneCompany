#!/usr/bin/env python3
"""Create fail-closed evidence for a disposable localhost Phase-1 preview."""
from __future__ import annotations

import argparse
import json
import re
import urllib.request
from urllib.parse import urlsplit

_SHA = re.compile(r"^[0-9a-f]{40}$")


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    """Prevent a localhost probe from following a redirect off the local target."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Reject every redirect; preview evidence must come from the selected root."""
        return None


def validate_local_url(url: str) -> str:
    """Return normalized localhost URL or reject any remote/credentialed target."""
    parts = urlsplit(url)
    if parts.scheme != "http" or parts.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError("LOCAL_PREVIEW_URL_REQUIRED")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("LOCAL_PREVIEW_URL_REQUIRED")
    if parts.port is None or not 1 <= parts.port <= 65535:
        raise ValueError("LOCAL_PREVIEW_PORT_REQUIRED")
    if parts.path not in {"", "/"}:
        raise ValueError("LOCAL_PREVIEW_ROOT_REQUIRED")
    return f"http://{parts.hostname}:{parts.port}/"


def collect(revision: str, url: str, timeout: float = 2.0) -> dict[str, object]:
    """Probe the local health endpoint and bind evidence to an exact git SHA."""
    if not isinstance(revision, str) or not _SHA.fullmatch(revision):
        raise ValueError("EXACT_REVISION_REQUIRED")
    root = validate_local_url(url)
    request = urllib.request.Request(root + "health", headers={"Host": urlsplit(root).netloc})
    opener = urllib.request.build_opener(_RejectRedirects)
    try:
        with opener.open(request, timeout=timeout) as response:
            payload = json.loads(response.read(4096).decode("utf-8"))
            status = response.status
    except Exception as exc:
        raise ValueError("LOCAL_PREVIEW_HEALTH_FAILED") from exc
    if status != 200 or payload != {"status": "ok", "scope": "local_disposable"}:
        raise ValueError("LOCAL_PREVIEW_HEALTH_FAILED")
    return {
        "schema": "onecompany.local-preview-evidence.v1",
        "revision": revision,
        "url": root,
        "health": "PASS",
        "scope": "local_disposable",
        "deployable": False,
    }


def main() -> int:
    """Collect and print one exact-revision local preview evidence document."""
    parser = argparse.ArgumentParser(description="Capture exact-revision localhost preview evidence")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    print(json.dumps(collect(args.revision, args.url), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
