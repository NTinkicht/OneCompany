#!/usr/bin/env python3
"""Serve an honest, read-only Phase-1 Mission Control projection on loopback."""
from __future__ import annotations

import argparse
import html
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

MAX_PROJECTION_BYTES = 65_536
EVIDENCE = ("quality", "preview", "browser", "ci", "review")


def _text(value: object, limit: int = 240) -> str:
    raw = value if isinstance(value, (str, int, float)) and not isinstance(value, bool) else ""
    return html.escape(str(raw)[:limit], quote=True)


def _preview_url(value: object) -> str | None:
    if not isinstance(value, str) or len(value) > 256:
        return None
    try:
        parts = urlsplit(value)
        if (parts.scheme != "http" or parts.hostname not in {"127.0.0.1", "localhost"}
                or parts.username or parts.password or parts.query or parts.fragment
                or parts.path not in ("", "/") or not 1 <= (parts.port or 0) <= 65535):
            return None
        return f"http://{parts.hostname}:{parts.port}/"
    except ValueError:
        return None


def _status(value: object) -> str:
    raw = value.get("status") if isinstance(value, dict) else value
    if raw in ("OBSERVED", "PENDING", "UNKNOWN"):
        return str(raw) + " (reported; not independently verified here)"
    if raw in ("PASS", "SUCCESS", "READY", "FAIL", "BLOCKED"):
        return str(raw) + " (unverified projection)"
    return "UNKNOWN (no confirmed evidence)"


def _evidence_value(projection: dict[str, object], key: str) -> object:
    """Adapt canonical v1 `checks` without inventing unsupported evidence."""
    direct = projection.get(key)
    if direct is not None:
        return direct
    checks = projection.get("checks")
    if not isinstance(checks, dict):
        return None
    # Canonical projection produces app/quality/preview HTTP evidence, NOT a real browser run.
    # Browser/CI/review remain UNKNOWN until their distinct producers supply them.
    canonical = {"quality": "quality", "preview": "preview"}.get(key)
    return checks.get(canonical) if canonical else None


def combine_projection_journey(projection: dict[str, object], journey: dict[str, object]) -> dict[str, object]:
    """Combine canonical producer outputs for display, without merging their authority."""
    if (not isinstance(projection, dict)
            or projection.get("schema") != "onecompany.mission-control.phase1.v1"
            or projection.get("authority_granted") is not False):
        raise ValueError("CANONICAL_UNAUTHORIZED_PROJECTION_REQUIRED")
    if (not isinstance(journey, dict)
            or journey.get("schema") != "onecompany.first-run-journey.v1"
            or journey.get("read_only") is not True
            or journey.get("approval") != "NOT_GRANTED"):
        raise ValueError("CANONICAL_READ_ONLY_JOURNEY_REQUIRED")
    combined = dict(projection)
    for key in ("project", "stage", "blockers", "steps", "next_action"):
        if key in journey:
            combined[key] = journey[key]
    combined["schema"] = "onecompany.mission-control-dashboard.phase1.v1"
    return combined


def render(projection: dict[str, object]) -> bytes:
    if not isinstance(projection, dict):
        raise ValueError("MISSION_CONTROL_PROJECTION_OBJECT_REQUIRED")
    project = projection.get("project")
    project = project if isinstance(project, dict) else {}
    name = _text(project.get("name") or projection.get("project_name") or "Unspecified project")
    revision = _text(projection.get("revision", "unknown"), 80)
    ready = projection.get("readiness") == "READY_FOR_OWNER_PREVIEW"
    status = "READY" if ready else "NOT READY"
    stage = _text(projection.get("stage") or "unknown")
    readiness = _text(projection.get("readiness") or "UNKNOWN")
    safe_url = _preview_url(projection.get("preview_url"))
    preview = _text(safe_url) if safe_url else "UNAVAILABLE (only validated localhost addresses displayed)"
    blockers = projection.get("blockers")
    if not isinstance(blockers, list):
        blockers = []
    blockers = [_text(item, 200) for item in blockers[:12] if isinstance(item, str)]
    block_html = ("".join("<li>" + item + "</li>" for item in blockers)
                  if blockers else "<li>No blockers supplied; this does not prove clear gates.</li>")
    cards = "".join(
        "<li><strong>" + _text("CI" if key == "ci" else key.title()) + "</strong>: "
        + _text(_status(_evidence_value(projection, key))) + "</li>"
        for key in EVIDENCE
    )
    steps = projection.get("steps")
    if not isinstance(steps, list):
        steps = []
    step_html = "".join(
        "<li>" + _text(item.get("title"), 120) + ": " + _text(item.get("status"), 60) + "</li>"
        for item in steps[:15] if isinstance(item, dict)
    ) or "<li>No guided steps supplied yet.</li>"
    next_action = _text(projection.get("next_action") or "Review actual evidence and confirm the next authorized step.")
    body = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OneCompany Mission Control</title></head>
<body><main><h1>Mission Control</h1><p>Project: <strong>{name}</strong></p>
<p id='status'>{status}</p><p>Reported preview readiness: {readiness}</p>
<p>Current guided stage: {stage}</p><p>Revision: <code>{revision}</code></p>
<section aria-labelledby="evidence"><h2 id="evidence">What has been observed?</h2>
<ul>{cards}</ul><p><strong>Projection fields are unverified input.</strong>
Displayed PASS or READY is not a verified GitHub gate or permission to release.</p></section>
<section aria-labelledby="preview"><h2 id="preview">Local preview</h2>
<p>{preview}</p><p>No remote or credential-bearing preview addresses are shown.</p></section>
<section aria-labelledby="steps"><h2 id="steps">Your next steps</h2><ol>{step_html}</ol></section>
<section aria-labelledby="blockers"><h2 id="blockers">Blockers</h2><ul>{block_html}</ul></section>
<p><strong>Next action:</strong> {next_action}</p>
<p>Read-only Phase-1 projection. No execution or deployment authority is granted.
Nothing here approves a Work Unit, lease, RunKey, model, merge or production release.</p>
</main></body></html>"""
    return body.encode("utf-8")


def serve(projection: dict[str, object], port: int = 0) -> ThreadingHTTPServer:
    page = render(projection)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            host = self.headers.get("Host", "").lower()
            if host not in {"127.0.0.1", "localhost", f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}:
                self.send_error(403); return
            if self.path != "/":
                self.send_error(404); return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers(); self.wfile.write(page)
        def log_message(self, *_args): return
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def _read_projection_file(path: Path) -> dict[str, object]:
    with path.open("rb") as source:
        raw = source.read(MAX_PROJECTION_BYTES + 1)
    if len(raw) > MAX_PROJECTION_BYTES:
        raise ValueError("MISSION_CONTROL_PROJECTION_TOO_LARGE")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("MISSION_CONTROL_PROJECTION_OBJECT_REQUIRED")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve local read-only Mission Control")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--journey", type=Path, help="Optional canonical read-only first-run journey JSON")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    try:
        projection = _read_projection_file(args.input)
        if args.journey is not None:
            journey = _read_projection_file(args.journey)
            projection = combine_projection_journey(projection, journey)
        server = serve(projection, args.port)
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        print("BLOCKED: " + str(exc), file=sys.stderr); return 2
    print(f"Mission Control: http://127.0.0.1:{server.server_port}/", flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
