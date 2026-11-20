"""Signals: a named, time-stamped series pulled out of snapshots or bag messages.

``Signal.at(t)`` interpolates linearly for analog signals and holds the last value for binary / count signals, and returns
None outside the recorded range (never extrapolates).

Paths use ``/`` as separator because PLC addresses contain dots: ``"base/deg"``, ``"bits/M30.1"``, ``"geom/tip/0"``.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field


@dataclass
class Signal:
    name: str
    t: list[float]
    v: list[float]
    kind: str = "analog"                  # analog | binary (value held between samples)
    unit: str = ""
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if len(self.t) != len(self.v):
            raise ValueError("t and v differ in length")
        if any(b < a for a, b in zip(self.t, self.t[1:])):
            raise ValueError(f"{self.name}: time stamps must not go backwards")

    def __len__(self) -> int:
        return len(self.t)

    @property
    def t0(self) -> float:
        return self.t[0]

    @property
    def t1(self) -> float:
        return self.t[-1]

    def at(self, t: float):
        if not self.t or t < self.t[0] or t > self.t[-1]:
            return None
        i = bisect_right(self.t, t) - 1
        if i >= len(self.t) - 1:
            return self.v[-1]
        if self.kind == "binary" or self.t[i + 1] == self.t[i]:
            return self.v[i]
        k = (t - self.t[i]) / (self.t[i + 1] - self.t[i])
        return self.v[i] + k * (self.v[i + 1] - self.v[i])

    def window(self, t_from: float, t_to: float) -> "Signal":
        pairs = [(a, b) for a, b in zip(self.t, self.v) if t_from <= a <= t_to]
        return Signal(self.name, [p[0] for p in pairs], [p[1] for p in pairs], self.kind, self.unit, self.meta)

    def shifted(self, dt: float) -> "Signal":
        """The same signal with every time stamp moved by ``dt`` seconds."""
        return Signal(self.name, [x + dt for x in self.t], list(self.v), self.kind, self.unit, self.meta)


def get_path(d, path: str):
    """``get_path(snapshot, "bits/M30.1")``; None when any part is missing."""
    cur = d
    for part in path.split("/"):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, (list, tuple)):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if cur is None:
            return None
    return cur


def from_frames(frames: list[dict], path: str, name: str | None = None, tkey: str = "t", kind: str = "analog", unit: str = "") -> Signal:
    """Signal from snapshots (each with a time key, default the snapshot's own ``t``). Frames without the value are skipped."""
    t, v = [], []
    for f in frames:
        x = get_path(f, path)
        if x is None:
            continue
        t.append(float(f[tkey]))
        v.append(float(x))
    return Signal(name or path, t, v, kind, unit)


def from_messages(messages, path: str, name: str | None = None, clock: str = "t_mono", kind: str = "analog", unit: str = "") -> Signal:
    """Signal from bag messages. ``clock``: ``t_mono`` / ``t_wall`` (message times) or ``payload`` (the snapshot's own ``t``)."""
    t, v = [], []
    for m in messages:
        x = get_path(m.payload, path)
        if x is None:
            continue
        t.append(float(m.payload["t"] if clock == "payload" else getattr(m, clock)))
        v.append(float(x))
    return Signal(name or path, t, v, kind, unit)


def rising_edges(sig: Signal, level: float = 0.5) -> list[float]:
    """Times (linearly interpolated between samples) at which the signal goes from below to at-or-above ``level``."""
    out = []
    for i in range(1, len(sig)):
        a, b = sig.v[i - 1], sig.v[i]
        if a < level <= b:
            if sig.kind == "binary" or b == a:
                out.append(sig.t[i])
            else:
                out.append(sig.t[i - 1] + (level - a) / (b - a) * (sig.t[i] - sig.t[i - 1]))
    return out


def falling_edges(sig: Signal, level: float = 0.5) -> list[float]:
    flipped = Signal(sig.name, sig.t, [-x for x in sig.v], sig.kind, sig.unit)
    return rising_edges(flipped, -level + 1e-12)
