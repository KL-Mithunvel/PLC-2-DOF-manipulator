"""HTTP/SSE front-end for the twin (standard library only).

  GET  /                          web UI (twin/web)
  GET  /api/state[?source=..]     one JSON snapshot
  GET  /api/stream?source=sim&ghost=replay|plc|mocap|...   Server-Sent Events, ~25 snapshots/s.
                                   ``source`` = primary (sim | replay), ``ghost`` = optional second pose source
  GET  /api/program               parsed ladder (IL) + PDO map
  GET  /api/watch                 current value of every operand used by the program
  GET  /api/sources               status of every registered source, recorder and log list
  POST /api/cmd                   {"type": "...", ...}; sim commands, plus record_*, replay_*, src
"""
from __future__ import annotations

import json
import mimetypes
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .sim import Twin
from .sources import LOG_DIR, Recorder, ReplaySource, list_logs

WEB = os.path.join(os.path.dirname(__file__), "web")


class Hub:
    """Owns the twin, the recorder, the replay source and any registered live sources."""

    def __init__(self, twin: Twin, log_dir: str = LOG_DIR) -> None:
        self.twin = twin
        self.recorder = Recorder(log_dir)                  # records the sim
        self.extra_rec: dict[str, Recorder] = {}            # one recorder per other source (plc, mocap, sensors ...)
        self._log_dir = log_dir
        self.replay = ReplaySource(log_dir)
        self.live: dict[str, object] = {}       # name -> object with snapshot()/status()/control()
        self._last_wall = time.perf_counter()

    def register(self, name: str, source) -> None:
        self.live[name] = source

    # called by the run loop
    def step(self) -> None:
        now = time.perf_counter()
        dt, self._last_wall = now - self._last_wall, now
        with self.twin.lock:
            self.twin.advance()
            if self.recorder.active:
                self.recorder.offer(self.twin.snapshot())
        for name, rec in self.extra_rec.items():
            if rec.active:
                snap = self.snapshot(name)
                if snap:
                    rec.offer(snap)
        self.replay.advance(dt)

    def snapshot(self, name: str) -> dict | None:
        if name == "sim":
            s = self.twin.snapshot()
            with self.twin.lock:
                s["sample"] = dict(self.twin.scope[-1]) if self.twin.scope else None
            sens = self.live.get("sensors")
            if sens:
                meas = sens.latest()
                s["sensors"] = meas
                if s["sample"]:
                    s["sample"]["base_a_meas"] = round(meas.get("base", {}).get("mA", 0) / 1000, 3)
                    s["sample"]["sh_a_meas"] = round(meas.get("shoulder", {}).get("mA", 0) / 1000, 3)
            return s
        if name == "replay":
            return self.replay.snapshot()
        src = self.live.get(name)
        return src.snapshot() if src else None

    def status(self) -> dict:
        return {
            "sources": ["sim", "replay"] + sorted(self.live),
            "recorder": {"active": self.recorder.active, "file": os.path.basename(self.recorder.path or ""), "frames": self.recorder.n},
            "recorders": {k: {"active": r.active, "file": os.path.basename(r.path or ""), "frames": r.n} for k, r in self.extra_rec.items()},
            "replay": {"file": self.replay.file, "playing": self.replay.playing, "speed": self.replay.speed,
                       "pos": self.replay.pos, "duration": self.replay.duration},
            "logs": list_logs(self.recorder.dir),
            "live": {k: v.status() for k, v in self.live.items()},
        }

    def command(self, c: dict) -> dict:
        t = c.get("type", "")
        if t in ("record_start", "record_stop"):
            src = c.get("source", "sim")
            if src == "sim":
                rec = self.recorder
            elif src in self.live:
                rec = self.extra_rec.setdefault(src, Recorder(self._log_dir))
            else:
                return {"ok": False, "error": "unknown source"}
            if t == "record_stop":
                rec.stop()
                return {"ok": True}
            return {"ok": True, "file": rec.start(c.get("name") or None)}
        if t == "replay_load":
            return {"ok": True, "frames": self.replay.load(c["file"])}
        if t == "replay_play":
            self.replay.playing = bool(c.get("on", True))
            return {"ok": True}
        if t == "replay_speed":
            self.replay.speed = max(0.05, min(20.0, float(c["value"])))
            return {"ok": True}
        if t == "replay_seek":
            self.replay.seek(float(c["frac"]))
            return {"ok": True}
        if t == "src":
            src = self.live.get(c.get("name"))
            if not src:
                return {"ok": False, "error": "unknown source"}
            return {"ok": True, **(src.control(c.get("action", ""), c) or {})}
        return self.twin.command(c)


def make_handler(hub: Hub):
    twin = hub.twin

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
            u = urlparse(self.path)
            path, q = u.path, {k: v[0] for k, v in parse_qs(u.query).items()}
            if path == "/api/state":
                return self._json(hub.snapshot(q.get("source", "sim")) or {})
            if path == "/api/program":
                return self._json(twin.program_info())
            if path == "/api/scope":
                with twin.lock:
                    return self._json(list(twin.scope))
            if path == "/api/sources":
                return self._json(hub.status())
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
                        src = q.get("source", "sim")
                        snap = hub.snapshot(src) or {"source": src, "empty": True}
                        if q.get("ghost") and q["ghost"] != "none":
                            snap["ghost"] = hub.snapshot(q["ghost"])
                        if n % 5 == 0:
                            if snap.get("source") == "sim":
                                with twin.lock:
                                    snap["watch"] = twin.plc.vm.operand_values()
                            snap["hub"] = hub.status()
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
            ctype = "text/javascript" if full.endswith((".js", ".mjs")) else (mimetypes.guess_type(full)[0] or "application/octet-stream")
            self.send_response(200)
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
                self._json(hub.command(cmd))
            except Exception as exc:   # noqa: BLE001
                self._json({"ok": False, "error": str(exc)}, 400)

    return H


def run(host: str = "127.0.0.1", port: int = 8765, persist: bool = True, open_browser: bool = False,
        hub_setup=None) -> None:
    twin = Twin(persist=persist)
    hub = Hub(twin)
    if hub_setup:
        hub_setup(hub)
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            hub.step()
            time.sleep(0.002)

    threading.Thread(target=loop, daemon=True).start()
    srv = ThreadingHTTPServer((host, port), make_handler(hub))
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
        hub.recorder.stop()
        for r in hub.extra_rec.values():
            r.stop()
        if persist:
            from .sim import STATE_FILE
            twin.plc.save_retentive(STATE_FILE)
