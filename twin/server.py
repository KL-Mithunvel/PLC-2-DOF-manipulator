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

    def __init__(self, twin: Twin, log_dir: str = LOG_DIR, record_format: str = "jsonl") -> None:
        self.twin = twin
        self.record_format = record_format                  # "jsonl" (one snapshot per line) | "bag" (bag/ package: MCAP or .bag.jsonl, with events)
        self._ev_n = twin.log_count
        self.recorder = self._new_recorder(log_dir)         # records the sim
        self.extra_rec: dict[str, Recorder] = {}            # one recorder per other source (plc, mocap, sensors ...)
        self._log_dir = log_dir
        self.replay = ReplaySource(log_dir)
        self.live: dict[str, object] = {}       # name -> object with snapshot()/status()/control()
        self.hmi_vnc = None                     # optional live.hmi_vnc.HmiVnc: view-only grab of the real HMI panel
        self._last_wall = time.perf_counter()
        self._diag_t = 0.0                      # last time diagnostics were written to the bag
        self._hmi_t = 0.0                       # last time a real-HMI frame was stored
        self._hmi_n = -1
        self.hmi_frame_period = 2.0             # seconds between stored HMI pictures
        self.step_stats = None                  # live.diag.Rolling of the hub loop period (set lazily)

    def _new_recorder(self, directory: str):
        if self.record_format == "bag":
            from bag import BagRecorder          # lazy: the standalone twin does not need the bag package unless asked
            return BagRecorder(directory)
        return Recorder(directory)

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
                new = self.twin.log_count - self._ev_n
                if new > 0 and hasattr(self.recorder, "event"):         # twin notes -> bag topic "events"
                    for line in list(self.twin.log)[-min(new, len(self.twin.log)):]:
                        self.recorder.event(line.strip())
            self._ev_n = self.twin.log_count
        for name, rec in self.extra_rec.items():
            if rec.active:
                snap = self.snapshot(name)
                if snap:
                    rec.offer(snap)
        self._side_channels(dt)
        self.replay.advance(dt)

    # ---- recording extras: raw blocks, events, diagnostics, HMI pictures --------------------------------------
    def _side_channels(self, dt: float) -> None:
        rec = self.recorder
        writing = rec.active and hasattr(rec, "write")
        if self.step_stats is None:
            from .diag import Rolling
            self.step_stats = Rolling(400)
        self.step_stats.add(dt * 1000)
        for name, src in self.live.items():
            raws = src.drain_raw() if hasattr(src, "drain_raw") else []
            evs = src.drain_events() if hasattr(src, "drain_events") else []
            if not writing:
                continue                                 # drained above so old data is never written into a later recording
            for r in raws:
                rec.write(f"{name}/raw", r, r.get("t_mono"), r.get("t_wall"))
            for e in evs:
                rec.write("events", {"text": e["text"], "kind": e["kind"], "source": name}, e.get("t_mono"), e.get("t_wall"))
        if not writing:
            return
        now = time.monotonic()
        if now - self._diag_t >= 1.0:
            self._diag_t = now
            for name, src in self.live.items():
                if hasattr(src, "diag"):
                    rec.write("diag", src.diag())
            rec.write("diag", {"source": "hub", "step_ms": self.step_stats.summary()})
        v = self.hmi_vnc
        if v is not None and v.png and v.frames != self._hmi_n and now - self._hmi_t >= self.hmi_frame_period:
            self._hmi_t, self._hmi_n = now, v.frames
            import hashlib
            folder = os.path.splitext(os.path.splitext(rec.path)[0])[0] + "_hmi" if rec.path else None
            rel = None
            if folder:
                os.makedirs(folder, exist_ok=True)
                rel = os.path.join(os.path.basename(folder), f"frame_{v.frames:06d}.png")
                with open(os.path.join(os.path.dirname(rec.path), rel), "wb") as fh:
                    fh.write(v.png)
            rec.write("hmi/frame", {"n": v.frames, "t_frame_wall": v.frame_t, "bytes": len(v.png),
                                    "sha": hashlib.sha256(v.png).hexdigest()[:16], "file": rel})

    def start_recording(self, name: str | None = None, meta: dict | None = None) -> dict:
        """One session file with every topic (twin state, every live source, raw PLC blocks, events, diagnostics, HMI pictures).
        Needs the bag format; with the old jsonl format each source gets its own file."""
        name = name or time.strftime("run_%Y%m%d_%H%M%S")
        if hasattr(self.recorder, "tap"):
            self.recorder.meta.update(meta or {})
            self.recorder.start(name)
            for src in self.live:
                self.extra_rec[src] = self.recorder.tap(src)
            self._diag_t = self._hmi_t = 0.0
            self._hmi_n = -1
            return {"ok": True, "file": self.recorder.path, "sources": ["sim", *self.live]}
        files = {"sim": self.recorder.start(f"{name}_sim")}
        for src in self.live:
            files[src] = self.extra_rec.setdefault(src, self._new_recorder(self._log_dir)).start(f"{name}_{src}")
        return {"ok": True, "files": files}

    def stop_recording(self) -> dict:
        self.recorder.stop()
        for r in self.extra_rec.values():
            r.stop()
        return {"ok": True}

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
            "hmi_vnc": self.hmi_vnc.status() if self.hmi_vnc else None,
        }

    def command(self, c: dict) -> dict:
        t = c.get("type", "")
        if t == "record_all":
            return self.start_recording(c.get("name") or None, {k: c[k] for k in ("notes", "payload_kg", "operator", "run") if k in c})
        if t == "record_stop_all":
            return self.stop_recording()
        if t in ("record_start", "record_stop"):
            src = c.get("source", "sim")
            if src == "sim":
                rec = self.recorder
            elif src in self.live:
                rec = self.extra_rec.setdefault(src, self._new_recorder(self._log_dir))
            else:
                return {"ok": False, "error": "unknown source"}
            if t == "record_stop":
                rec.stop()
                return {"ok": True}
            if hasattr(rec, "meta"):
                rec.meta.update({k: c[k] for k in ("notes", "payload_kg", "operator", "run") if k in c})
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
            if path == "/api/hmi.png":
                png = hub.hmi_vnc.png if hub.hmi_vnc else None
                if not png:
                    return self.send_error(404)
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(png)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(png)
                return
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
        hub_setup=None, query: str = "", record_format: str = "jsonl") -> None:
    twin = Twin(persist=persist)
    hub = Hub(twin, record_format=record_format)
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
        webbrowser.open(url + query)
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
