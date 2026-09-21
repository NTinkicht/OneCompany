#!/usr/bin/env python3
"""Disposable local sign-inless CRUD application for OneCompany Phase 1.

No production auth, remote bind, durable data, network dependencies or paid
provider. The local fixture exists to establish real app-run and HTTP evidence.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

MAX_BODY = 4096
MAX_TITLE = 120
PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport"
content="width=device-width,initial-scale=1"><title>OneCompany Local Checklist</title>
<link rel="stylesheet" href="/app.css"></head>
<body><main><h1>My checklist</h1><p>A local demonstration. Items disappear when
the server stops.</p><form id="add"><label for="title">New item</label>
<input id="title" maxlength="120" required autocomplete="off">
<button>Add</button></form><p id="message" role="status" aria-live="polite"></p>
<ul id="items" aria-label="Checklist items"></ul></main>
<script src="/app.js" defer></script></body></html>
"""
CSS = """body{font:1rem/1.5 system-ui,sans-serif;max-width:42rem;margin:2rem auto;
padding:0 1rem;background:#f6f8fb;color:#19273c}main{padding:1.5rem;
border:1px solid #d4dce8;border-radius:1rem;background:white}
input{font:inherit;width:65%;padding:.5rem}button{font:inherit;padding:.5rem;
margin:.3rem;cursor:pointer}li{padding:.5rem;border-bottom:1px solid #ddd}
li.done>span{text-decoration:line-through}button:focus-visible,input:focus-visible
{outline:3px solid #185bc1;outline-offset:2px}
"""
JS = """const list=document.getElementById('items');
const status=document.getElementById('message');
async function call(url,method='GET',body){
 const response=await fetch(url,{method,headers:{
  'X-OneCompany-Local':'1','Content-Type':'application/json'
 },body:body===undefined?undefined:JSON.stringify(body)});
 const data=await response.json();
 if(!response.ok)throw Error(data.error||'Request failed');
 return data;
}
async function refresh(){
 const data=await call('/api/items');list.replaceChildren();
 for(const item of data.items){
  const li=document.createElement('li');if(item.done)li.className='done';
  const text=document.createElement('span');text.textContent=item.title;
  const toggle=document.createElement('button');toggle.textContent=item.done?'Undo':'Done';
  toggle.setAttribute('aria-label',(item.done?'Undo ':'Complete ')+item.title);
  toggle.addEventListener('click',async()=>{
   try{await call('/api/items/'+item.id,'PATCH',{done:!item.done});await refresh()}
   catch(error){status.textContent=error.message}
  });
  const remove=document.createElement('button');remove.textContent='Delete';
  remove.setAttribute('aria-label','Delete '+item.title);
  remove.addEventListener('click',async()=>{
   try{await call('/api/items/'+item.id,'DELETE');await refresh()}
   catch(error){status.textContent=error.message}
  });
  li.append(text,toggle,remove);list.append(li);
 }
}
document.getElementById('add').addEventListener('submit',async(event)=>{
 event.preventDefault();const field=document.getElementById('title');
 try{await call('/api/items','POST',{title:field.value});field.value='';
  status.textContent='Item added';await refresh()}
 catch(error){status.textContent=error.message}
});
refresh().catch(error=>status.textContent=error.message);
"""


class ItemStore:
    """SQLite in memory with one lock across every DB operation."""
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY,"
                        "title TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0)")

    def list(self) -> list[dict]:
        with self.lock:
            records = self.db.execute(
                "SELECT id,title,done FROM items ORDER BY id"
            ).fetchall()
        return [dict(id=r["id"], title=r["title"], done=bool(r["done"]))
                for r in records]

    def create(self, title: str) -> dict:
        with self.lock:
            cursor = self.db.execute(
                "INSERT INTO items(title,done) VALUES (?,0)", (title,)
            )
            self.db.commit()
            return dict(id=cursor.lastrowid, title=title, done=False)

    def set_done(self, item_id: int, done: bool) -> bool:
        with self.lock:
            cursor = self.db.execute(
                "UPDATE items SET done=? WHERE id=?",
                (int(done), item_id),
            )
            self.db.commit()
            return cursor.rowcount == 1

    def remove(self, item_id: int) -> bool:
        with self.lock:
            cursor = self.db.execute("DELETE FROM items WHERE id=?", (item_id,))
            self.db.commit()
            return cursor.rowcount == 1

    def close(self) -> None:
        with self.lock:
            self.db.close()


def make_handler(store: ItemStore) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "OneCompanyFixture/1"
        sys_version = ""

        def log_message(self, fmt: str, *args: object) -> None:
            # Avoid logging user-provided titles/URLs in fixture output.
            pass

        def respond(self, status: int, payload: object,
                    content_type: str = "application/json; charset=utf-8") -> None:
            data = (payload.encode("utf-8") if isinstance(payload, str) else
                    json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; script-src 'self'; "
                             "style-src 'self'; connect-src 'self'; "
                             "img-src 'self'; base-uri 'none'; "
                             "form-action 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def valid_local_request(self) -> bool:
            host = self.headers.get("Host", "").lower()
            if host not in ("localhost", "127.0.0.1",
                            f"localhost:{self.server.server_port}",
                            f"127.0.0.1:{self.server.server_port}"):
                self.respond(403, {"error": "local host only"})
                return False
            origin = self.headers.get("Origin")
            if origin is not None:
                parts = urlsplit(origin)
                if (parts.scheme != "http" or
                    parts.netloc.lower() not in (
                        f"localhost:{self.server.server_port}",
                        f"127.0.0.1:{self.server.server_port}",
                    ) or parts.path not in ("", "/") or
                    parts.query or parts.fragment):
                    self.respond(403, {"error": "cross-origin writes refused"})
                    return False
            return True

        def mutation_allowed(self) -> bool:
            if self.headers.get("X-OneCompany-Local") != "1":
                self.respond(403, {"error": "local request header required"})
                return False
            return True

        def body(self) -> object | None:
            length = self.headers.get("Content-Length", "")
            if not length.isdecimal() or int(length) > MAX_BODY:
                self.respond(413, {"error": "bounded body required"})
                return None
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                self.respond(415, {"error": "application/json required"})
                return None
            try:
                return json.loads(self.rfile.read(int(length)).decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                self.respond(400, {"error": "invalid JSON"})
                return None

        def route_id(self) -> int | None:
            base = "/api/items/"
            if not self.path.startswith(base):
                self.respond(404, {"error": "not found"})
                return None
            raw = self.path[len(base):]
            if not raw.isdecimal() or len(raw) > 10 or int(raw) < 1:
                self.respond(400, {"error": "invalid item id"})
                return None
            return int(raw)

        def do_GET(self) -> None:
            if not self.valid_local_request():
                return
            if self.path == "/":
                self.respond(200, PAGE, "text/html; charset=utf-8")
            elif self.path == "/app.css":
                self.respond(200, CSS, "text/css; charset=utf-8")
            elif self.path == "/app.js":
                self.respond(200, JS, "text/javascript; charset=utf-8")
            elif self.path == "/health":
                self.respond(200, {"status": "ok", "scope": "local_disposable"})
            elif self.path == "/api/items":
                self.respond(200, {"items": store.list()})
            else:
                self.respond(404, {"error": "not found"})

        def do_POST(self) -> None:
            if not self.valid_local_request() or not self.mutation_allowed():
                return
            if self.path != "/api/items":
                self.respond(404, {"error": "not found"})
                return
            payload = self.body()
            if payload is None:
                return
            if (not isinstance(payload, dict) or set(payload) != {"title"} or
                not isinstance(payload["title"], str) or
                not 1 <= len(payload["title"].strip()) <= MAX_TITLE or
                any(ord(char) < 32 or ord(char) == 127
                    for char in payload["title"])):
                self.respond(400, {"error": "title must be 1–120 printable characters"})
                return
            self.respond(201, store.create(payload["title"].strip()))

        def do_PATCH(self) -> None:
            if not self.valid_local_request() or not self.mutation_allowed():
                return
            item_id = self.route_id()
            if item_id is None:
                return
            payload = self.body()
            if payload is None:
                return
            if not isinstance(payload, dict) or set(payload) != {"done"} or type(payload["done"]) is not bool:
                self.respond(400, {"error": "done must be true or false"})
                return
            self.respond(
                200 if store.set_done(item_id, payload["done"]) else 404,
                {"ok": True} if item_id in [x["id"] for x in store.list()]
                else {"error": "item not found"},
            )

        def do_DELETE(self) -> None:
            if not self.valid_local_request() or not self.mutation_allowed():
                return
            item_id = self.route_id()
            if item_id is None:
                return
            if store.remove(item_id):
                self.respond(200, {"ok": True})
            else:
                self.respond(404, {"error": "item not found"})

        def do_OPTIONS(self) -> None:
            self.respond(405, {"error": "cross-origin requests not supported"})

    return Handler


def start_server(port: int = 8765) -> tuple[ThreadingHTTPServer, ItemStore]:
    if not 0 <= port <= 65535:
        raise ValueError("port must be in 0..65535")
    store = ItemStore()
    try:
        server = ThreadingHTTPServer(
            ("127.0.0.1", port), make_handler(store)
        )
    except BaseException:
        store.close()
        raise
    server.daemon_threads = True
    return server, store


def main() -> int:
    parser = argparse.ArgumentParser(description="Run disposable local checklist preview")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server, store = start_server(args.port)
    print(f"Local-only fixture: http://127.0.0.1:{server.server_port}/", flush=True)
    print("Use Ctrl+C to stop; in-memory data is discarded.", flush=True)
    try:
        server.serve_forever(poll_interval=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
