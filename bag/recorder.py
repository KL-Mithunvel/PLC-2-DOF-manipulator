"""Drop-in replacement for ``twin.sources.Recorder`` that writes bag files.

Same interface (start / stop / offer / active / path / n), so the Hub can use either. ``offer`` writes the snapshot to the
topic ``<source>/state`` (``twin/state`` for the simulation) at most every ``period`` seconds of source time.
Extra topics (events, diag) go through ``write``.
"""
from __future__ import annotations

import os
import time

from .core import BagWriter, mcap_available
from .meta import collect_meta

_STRIP = ("watch", "log")
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
_TOPIC = {"sim": "twin/state", "plc": "plc/decoded", "mocap": "mocap/pose", "sensors": "sensors"}


class BagRecorder:
    def __init__(self, directory: str = LOG_DIR, fmt: str = "auto", meta: dict | None = None, period: float = 0.04) -> None:
        self.dir, self.fmt, self.period = directory, fmt, period
        self.meta = dict(meta or {})
        self.writer: BagWriter | None = None
        self.path: str | None = None
        self.n = 0
        self._last_t = -1e9

    @property
    def active(self) -> bool:
        return self.writer is not None

    def start(self, name: str | None = None) -> str:
        self.stop()
        name = name or time.strftime("run_%Y%m%d_%H%M%S")
        fmt = self.fmt if self.fmt != "auto" else ("mcap" if mcap_available() else "jsonl")
        self.writer = BagWriter(os.path.join(self.dir, name), collect_meta(**self.meta), fmt=fmt)
        self.path = self.writer.path
        self.n, self._last_t = 0, -1e9
        return self.path

    def stop(self) -> None:
        if self.writer:
            self.writer.close()
        self.writer = None

    def offer(self, snap: dict) -> None:
        if not self.writer or snap["t"] - self._last_t < self.period:
            return
        self._last_t = snap["t"]
        self.writer.write(_TOPIC.get(snap.get("source", "sim"), snap.get("source", "sim") + "/state"),
                          {k: v for k, v in snap.items() if k not in _STRIP})
        self.n += 1
        if self.n % 50 == 0:
            self.writer.flush()

    def write(self, topic: str, payload: dict) -> None:
        """Write any other topic (events, diag) with the current clock."""
        if self.writer:
            self.writer.write(topic, payload)

    def event(self, text: str, kind: str = "info") -> None:
        self.write("events", {"text": text, "kind": kind})
