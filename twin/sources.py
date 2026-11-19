"""Data bus pieces: snapshot recorder, replay source, and the helper that turns a joint pose into a
minimal "ghost-compatible" snapshot (used by the live PLC, mocap and replay sources).

Snapshot schema v1: see docs/SCHEMA.md.  Every snapshot carries ``schema``, ``source``, ``t`` (source
seconds) and ``wall`` (unix time).
"""
from __future__ import annotations

import glob
import json
import math
import os
import threading
import time

SCHEMA = 1
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
_STRIP = ("watch", "log")


def pose_snapshot(source: str, cfg, base_deg: float, shoulder_deg: float, t: float | None = None,
                  magnet: bool = False, extra: dict | None = None) -> dict:
    """Minimal snapshot (enough for the 3D ghost arm and error overlays) from two joint angles."""
    from .config import TwinCfg  # noqa: F401  (type only)
    a = cfg.arm
    phi, th = math.radians(base_deg), math.radians(shoulder_deg)
    r = a.reach * math.sin(th)
    p = [r * math.cos(phi), r * math.sin(phi), a.shoulder_height + a.reach * math.cos(th)]
    snap = {
        "schema": SCHEMA, "source": source, "t": t if t is not None else time.time(), "wall": time.time(),
        "base": {"deg": base_deg}, "shoulder": {"deg": shoulder_deg, "load_pct": 0.0},
        "geom": {"shoulder": [0, 0, a.shoulder_height], "p": p, "tip": [p[0], p[1], p[2] - a.drop_link]},
        "io": {"Q0.7": int(magnet)},
        "geo_cfg": {"reach": a.reach, "h": a.shoulder_height, "drop": a.drop_link,
                    "part_r": a.part_radius, "part_h": a.part_height},
    }
    if extra:
        snap.update(extra)
    return snap


class Recorder:
    """Appends snapshots (JSON lines) to logs/<name>.jsonl."""

    def __init__(self, directory: str = LOG_DIR) -> None:
        self.dir = directory
        self.fh = None
        self.path: str | None = None
        self.n = 0
        self._last_t = -1e9
        self.period = 0.04

    @property
    def active(self) -> bool:
        return self.fh is not None

    def start(self, name: str | None = None) -> str:
        self.stop()
        os.makedirs(self.dir, exist_ok=True)
        name = name or time.strftime("run_%Y%m%d_%H%M%S")
        self.path = os.path.join(self.dir, name + ".jsonl")
        self.fh = open(self.path, "w", encoding="utf-8")
        self.n, self._last_t = 0, -1e9
        return self.path

    def stop(self) -> None:
        if self.fh:
            self.fh.close()
        self.fh = None

    def offer(self, snap: dict) -> None:
        """Write the snapshot if at least ``period`` of source time has passed."""
        if not self.fh or snap["t"] - self._last_t < self.period:
            return
        self._last_t = snap["t"]
        self.fh.write(json.dumps({k: v for k, v in snap.items() if k not in _STRIP}, separators=(",", ":")) + "\n")
        self.n += 1
        if self.n % 50 == 0:
            self.fh.flush()


def list_logs(directory: str = LOG_DIR) -> list[str]:
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(directory, "*.jsonl")))


class ReplaySource:
    name = "replay"

    def __init__(self, directory: str = LOG_DIR) -> None:
        self.dir = directory
        self.frames: list[dict] = []
        self.file = ""
        self.pos = 0.0           # seconds from start
        self.playing = False
        self.speed = 1.0
        self.loop = True
        self.lock = threading.RLock()

    def load(self, name: str) -> int:
        path = os.path.join(self.dir, os.path.basename(name))      # no path traversal
        with open(path, encoding="utf-8") as fh:
            frames = [json.loads(line) for line in fh if line.strip()]
        with self.lock:
            self.frames, self.file, self.pos, self.playing = frames, os.path.basename(path), 0.0, True
        return len(frames)

    @property
    def duration(self) -> float:
        return (self.frames[-1]["t"] - self.frames[0]["t"]) if len(self.frames) > 1 else 0.0

    def advance(self, wall_dt: float) -> None:
        with self.lock:
            if not self.playing or not self.frames:
                return
            self.pos += wall_dt * self.speed
            if self.pos > self.duration:
                if self.loop:
                    self.pos = 0.0
                else:
                    self.pos, self.playing = self.duration, False

    def seek(self, frac: float) -> None:
        with self.lock:
            self.pos = max(0.0, min(1.0, frac)) * self.duration

    def snapshot(self) -> dict | None:
        with self.lock:
            if not self.frames:
                return None
            t = self.frames[0]["t"] + self.pos
            lo, hi = 0, len(self.frames) - 1
            while lo < hi:                       # first frame with frame.t >= t
                mid = (lo + hi) // 2
                if self.frames[mid]["t"] < t:
                    lo = mid + 1
                else:
                    hi = mid
            snap = dict(self.frames[lo])
            snap["source"] = "replay"
            snap["replay"] = {"file": self.file, "pos": self.pos, "duration": self.duration, "playing": self.playing,
                              "speed": self.speed, "index": lo, "n": len(self.frames)}
            return snap
