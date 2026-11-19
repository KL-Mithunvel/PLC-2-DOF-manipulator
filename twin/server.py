"""HTTP/SSE front-end for the twin (standard library only).

  GET  /                 web UI (twin/web)
  GET  /api/state        one JSON snapshot
  GET  /api/stream       Server-Sent Events, ~25 snapshots/s  (what a three.js view should subscribe to)
  GET  /api/program      the parsed ladder (IL) + PDO map
  GET  /api/watch        current value of every operand used by the program
  POST /api/cmd          {"type": "...", ...}  see Twin.command
"""
from __future__ import annotations

import json
import mimetypes
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .sim import Twin

WEB = os.path.join(os.path.dirname(__file__), "web")


def make_handler(twin: Twin):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):  # quiet
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj, separators=(",", ":")).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/api/state":
                return self._json(self._snap())
            if path == "/api/program":
                return self._json(twin.program_info())
            if path == "/api/watch":
                with twin.lock:
                    return self._json(twin.plc.vm.operand_values())
            if path == "/api/stream":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                try:
                    n = 0
                    while True:
                        snap = self._snap()
                        if n % 5 == 0:
                            with twin.lock:
                                snap["watch"] = twin.plc.vm.operand_values()
                        self.wfile.write(b"data: " + json.dumps(snap, separators=(",", ":")).encode() + b"\n\n")
                        self.wfile.flush()
                        n += 1
                        time.sleep(0.04)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return
            rel = "index.html" if path == "/" else path.lstrip("/")
            full = os.path.normpath(os.path.join(WEB, rel))
            if not full.startswith(WEB) or not os.path.isfile(full):
                self.send_error(404)
                return
            with open(full, "rb") as fh:
                data = fh.read()
            self.send_response(200)
            ctype = "text/javascript" if full.endswith((".js", ".mjs")) else (mimetypes.guess_type(full)[0] or "application/octet-stream")
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            if self.path != "/api/cmd":
                return self.send_error(404)
            n = int(self.headers.get("Content-Length", 0))
            try:
                cmd = json.loads(self.rfile.read(n) or b"{}")
                self._json(twin.command(cmd))
            except Exception as exc:   # noqa: BLE001
                self._json({"ok": False, "error": str(exc)}, 400)

        def _snap(self):
            s = twin.snapshot()
            with twin.lock:
                s["sample"] = twin.scope[-1] if twin.scope else None
            return s

    return H


def run(host: str = "127.0.0.1", port: int = 8765, persist: bool = True, open_browser: bool = False) -> None:
    twin = Twin(persist=persist)
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            with twin.lock:
                twin.advance()
            time.sleep(0.002)

    threading.Thread(target=loop, daemon=True).start()
    srv = ThreadingHTTPServer((host, port), make_handler(twin))
    srv.daemon_threads = True
    url = f"http://{host}:{port}/"
    print(f"Digital twin running at {url}   (Ctrl+C to stop)")
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        if persist:
            twin.plc.save_retentive(__import__("twin.sim", fromlist=["STATE_FILE"]).STATE_FILE)
