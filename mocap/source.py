"""Live / file video -> bus source "mocap" (shown as the ghost arm, recorded like any other source)."""
from __future__ import annotations

import threading
import time

import cv2

from twin.config import TwinCfg
from twin.sources import pose_snapshot

from .tracker import Camera, Tracker


class MocapSource:
    name = "mocap"

    def __init__(self, frames, camera: Camera, cfg: TwinCfg | None = None, layout=None, label: str = "") -> None:
        """frames: callable(stop_event) -> iterator of (timestamp_seconds, BGR/gray image)."""
        self.frames = frames
        self.cfg = cfg or TwinCfg()
        self.tracker = Tracker(camera, layout, self.cfg.arm.shoulder_height)
        self.label = label
        self.latest = None
        self.seen = 0
        self.lost = 0
        self.last_wall = 0.0
        self.proc_ms = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @classmethod
    def from_spec(cls, spec: str, camera: Camera, cfg: TwinCfg | None = None) -> "MocapSource":
        """spec: camera index ("0") or a video file path."""
        def gen(stop):
            cap = cv2.VideoCapture(int(spec) if spec.isdigit() else spec)
            is_file = not spec.isdigit()
            fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
            t0 = time.time()
            n = 0
            while not stop.is_set():
                ok, img = cap.read()
                if not ok:
                    if is_file:
                        break
                    time.sleep(0.05)
                    continue
                if is_file:                      # play files in real time
                    due = t0 + n / fps
                    time.sleep(max(0.0, due - time.time()))
                n += 1
                yield (time.time() if not is_file else t0 + n / fps), img
            cap.release()
        return cls(gen, camera, cfg, label=spec)

    def start(self) -> "MocapSource":
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)          # releases the video file / camera handle

    def _run(self) -> None:
        for ts, img in self.frames(self._stop):
            t0 = time.perf_counter()
            est = self.tracker.estimate(img)
            self.proc_ms = (time.perf_counter() - t0) * 1000
            if est is None:
                self.lost += 1
                continue
            self.seen += 1
            self.last_wall = time.time()
            self.latest = (ts, est)

    def process(self, ts: float, img) -> bool:
        """Synchronous variant for scripts/tests."""
        est = self.tracker.estimate(img)
        if est is None:
            self.lost += 1
            return False
        self.seen += 1
        self.last_wall = time.time()
        self.latest = (ts, est)
        return True

    def snapshot(self) -> dict | None:
        if not self.latest:
            return None
        ts, e = self.latest
        extra = {"mocap": {"tags": e.tags, "resid_mm": e.resid_mm, "per_tag_deg": e.per_tag_deg, "proc_ms": self.proc_ms}}
        if e.part_world:
            extra["mocap"]["part_world"] = e.part_world
        return pose_snapshot("mocap", self.cfg, e.base_deg, e.shoulder_deg, t=ts, extra=extra)

    def status(self) -> dict:
        ok = bool(self.last_wall) and time.time() - self.last_wall < 1.5
        return {"connected": ok, "info": f"{self.label} tracked={self.seen} lost={self.lost} {self.proc_ms:.0f} ms/frame"}

    def control(self, action: str, params: dict) -> dict:
        return {}
