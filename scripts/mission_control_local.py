#!/usr/bin/env python3
"""Serve a read-only Phase-1 Mission Control readiness view on loopback only."""
from __future__ import annotations

import argparse
import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def render(projection: dict[str, object]) -> bytes:
    """Render a compact, escaped status page without granting authority."""
    revision = html.escape(str(projection.get("revision", "unknown")))
    ready = projection.get("readiness") == "READY_FOR_OWNER_PREVIEW"
    status = "READY" if ready else "NOT READY"
    body = f"""<!doctype html><html><head><meta charset='utf-8'><title>OneCompany Mission Control</title></head>
<body><main><h1>Mission Control</h1><p id='status'>{status}</p><p>Revision: <code>{revision}</code></p>
<p>Read-only Phase-1 projection. No execution or deployment authority is granted.</p></main></body></html>"""
    return body.encode("utf-8")


def serve(projection: dict[str, object], port: int = 0) -> ThreadingHTTPServer:
    """Create a loopback-only HTTP server for the supplied readiness projection."""
    page = render(projection)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/":
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, *_args):
            return

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main() -> int:
    """Load an existing projection and serve it locally without mutation."""
    parser = argparse.ArgumentParser(description="Serve local read-only Mission Control")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    projection = json.loads(args.input.read_text(encoding="utf-8"))
    server = serve(projection, args.port)
    print(f"Mission Control: http://127.0.0.1:{server.server_port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
