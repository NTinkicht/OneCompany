#!/usr/bin/env python3
"""OneCompany's disposable, zero-credential, loopback-only real-app fixture."""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
MAX_BODY = 2048
ID = re.compile(r"/api/items/([1-9][0-9]{0,9})\Z")


def valid_title(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("title must be text")
    title = value.strip()
    if not (1 <= len(title) <= 120) or any(ord(c) < 32 or ord(c) == 127 for c in title):
        raise ValueError("title must be 1-120 characters with no controls")
    return title


class VerticalServer(HTTPServer):
    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        if host != "127.0.0.1":
            raise ValueError("only explicit IPv4 loopback is allowed")
        self.db = sqlite3.connect(":memory:", check_same_thread=False)  # one synchronous HTTPServer thread; tests construct the fixture in their caller thread
        self.db.execute(
            "CREATE TABLE items (id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " title TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0)"
        )
        super().__init__((host, port), Handler)

    def server_close(self) -> None:
        try:
            super().server_close()
        finally:
            self.db.close()


class Handler(BaseHTTPRequestHandler):
    server: VerticalServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: object) -> None:
        # No user-submitted titles, bodies or credentials enter logs.
        pass

    def reply(self, code: int, data: dict | bytes | None = None, mime: str = "application/json") -> None:
        if data is None:
            body = b""
        elif isinstance(data, bytes):
            body = data
        else:
            body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", mime + ("; charset=utf-8" if mime.startswith("text/") else ""))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; object-src 'none'; base-uri 'none'")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        if self.command != "HEAD" and body:
            self.wfile.write(body)

    def reject(self, code: int, reason: str) -> None:
        self.reply(code, {"error": reason})

    def path_only(self) -> str:
        parsed = urlsplit(self.path)
        if parsed.query or parsed.fragment:
            return ""  # no silently ignored params
        return parsed.path

    def same_origin(self) -> bool:
        host = self.headers.get("Host", "")
        return host == f"127.0.0.1:{self.server.server_port}"

    def item_id(self, path: str) -> int | None:
        match = ID.fullmatch(path)
        if match is None:
            return None
        value = int(match.group(1))
        return value if value <= 2**31 - 1 else None

    def lookup(self, item_id: int) -> dict | None:
        row = self.server.db.execute(
            "SELECT id, title, done FROM items WHERE id = ?", (item_id,)
        ).fetchone()
        return {"id": row[0], "title": row[1], "done": bool(row[2])} if row else None

    def payload(self) -> dict:
        if self.headers.get("Content-Type", "").split(";", 1)[0].lower() != "application/json":
            raise ValueError("Content-Type must be application/json")
        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError as exc:
            raise ValueError("invalid content length") from exc
        if length < 1 or length > MAX_BODY:
            self.close_connection = True
            raise ValueError("JSON body missing or too large")
        raw = self.rfile.read(length)
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid JSON") from exc
        if not isinstance(result, dict):
            raise ValueError("JSON object required")
        return result

    def do_GET(self) -> None:
        if not self.same_origin():
            self.reject(400, "invalid Host")
            return
        path = self.path_only()
        if path == "/healthz":
            self.reply(200, {"status": "ready", "scope": "local_demo_only"})
        elif path == "/api/items":
            rows = self.server.db.execute("SELECT id, title, done FROM items ORDER BY id").fetchall()
            self.reply(200, {"items": [
                {"id": i, "title": title, "done": bool(done)} for i, title, done in rows
            ]})
        elif path in ("/", "/app.js"):
            file = HERE / ("index.html" if path == "/" else "app.js")
            mime = "text/html" if path == "/" else "text/javascript"
            self.reply(200, file.read_bytes(), mime)
        elif path.startswith("/api/items/") and self.item_id(path) is not None:
            item = self.lookup(self.item_id(path))
            self.reply(200, item) if item else self.reject(404, "item not found")
        else:
            self.reject(404, "route not found")

    def do_POST(self) -> None:
        if not self.same_origin():
            self.reject(400, "invalid Host")
            return
        if self.path_only() != "/api/items":
            self.reject(404, "route not found")
            return
        try:
            body = self.payload()
            if set(body) != {"title"}:
                raise ValueError("only title is allowed")
            title = valid_title(body["title"])
        except ValueError as exc:
            self.reject(400, str(exc))
            return
        cursor = self.server.db.execute("INSERT INTO items(title) VALUES(?)", (title,))
        self.server.db.commit()
        self.reply(201, self.lookup(cursor.lastrowid))

    def do_PATCH(self) -> None:
        if not self.same_origin():
            self.reject(400, "invalid Host")
            return
        item_id = self.item_id(self.path_only())
        if item_id is None:
            self.reject(404, "route not found")
            return
        if self.lookup(item_id) is None:
            self.reject(404, "item not found")
            return
        try:
            body = self.payload()
            if not body or set(body) - {"title", "done"}:
                raise ValueError("only title and done are allowed")
            title = valid_title(body["title"]) if "title" in body else None
            done = body.get("done")
            if "done" in body and type(done) is not bool:
                raise ValueError("done must be a boolean")
        except ValueError as exc:
            self.reject(400, str(exc))
            return
        if title is not None:
            self.server.db.execute("UPDATE items SET title=? WHERE id=?", (title, item_id))
        if "done" in body:
            self.server.db.execute("UPDATE items SET done=? WHERE id=?", (int(done), item_id))
        self.server.db.commit()
        self.reply(200, self.lookup(item_id))

    def do_DELETE(self) -> None:
        if not self.same_origin():
            self.reject(400, "invalid Host")
            return
        item_id = self.item_id(self.path_only())
        if item_id is None:
            self.reject(404, "route not found")
            return
        if self.lookup(item_id) is None:
            self.reject(404, "item not found")
            return
        self.server.db.execute("DELETE FROM items WHERE id=?", (item_id,))
        self.server.db.commit()
        self.reply(204)

    def do_PUT(self) -> None:
        self.reject(405, "method not supported")

    def do_OPTIONS(self) -> None:
        self.reject(405, "no cross-origin access")


def main() -> int:
    parser = argparse.ArgumentParser(description="Loopback-only disposable OneCompany app demo")
    parser.add_argument("--port", type=int, default=8765, help="0 for ephemeral OS-chosen port")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("port must be 0..65535")
    with VerticalServer(port=args.port) as server:
        print(f"Local demo only: http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever(poll_interval=0.05)
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
