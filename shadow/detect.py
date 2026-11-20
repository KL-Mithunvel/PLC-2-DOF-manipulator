"""Detectors that turn a residual into alarms, and the event log that collects them.

* ``Threshold(limit, hold_s)``       |r| above a limit continuously for at least ``hold_s``.
* ``Cusum(k, h, baseline_s)``        two-sided CUSUM on the standardised residual: finds small persistent shifts (drift, bias) early.
                                     ``k`` = allowance in sigma, ``h`` = decision limit in sigma. Defaults k=0.5, h=10 give an
                                     average run length of about 1e5 samples on white noise. Real residuals are correlated, so
                                     expect more false alarms than the white-noise figure: measure on clean runs (docs/RESEARCH_ANGLES.md).
* ``WindowRms(window_s, limit)``     RMS over a sliding window above a limit (sustained error rather than spikes).

Every detector has ``run(t, r) -> list[Alarm]``. Standard library only.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import asdict, dataclass

from .residual import Residual


@dataclass
class Alarm:
    detector: str
    signal: str
    t_start: float
    t_end: float
    peak: float
    severity: str = "warn"        # info | warn | alarm
    detail: str = ""

    def to_event(self) -> dict:
        return {"kind": "divergence", "severity": self.severity,
                "text": f"{self.signal}: {self.detector} {self.detail} ({self.t_start:.2f}..{self.t_end:.2f} s, peak {self.peak:.3g})",
                **{k: v for k, v in asdict(self).items() if k not in ("detail",)}}


class Threshold:
    def __init__(self, limit: float, hold_s: float = 0.0, severity: str = "alarm") -> None:
        self.limit, self.hold_s, self.severity = limit, hold_s, severity
        self.name = f"threshold>{limit:g}"

    def run(self, t: list[float], r: list[float], signal: str = "") -> list[Alarm]:
        out, start, peak, last = [], None, 0.0, None
        for x, v in zip(t, r):
            if abs(v) > self.limit:
                if start is None:
                    start, peak = x, 0.0
                peak = max(peak, abs(v))
                last = x
            elif start is not None:
                if last - start >= self.hold_s:
                    out.append(Alarm(self.name, signal, start, last, peak, self.severity))
                start = None
        if start is not None and last - start >= self.hold_s:
            out.append(Alarm(self.name, signal, start, last, peak, self.severity))
        return out


class Cusum:
    def __init__(self, k: float = 0.5, h: float = 10.0, baseline_s: float = 10.0, min_sigma: float = 1e-9, severity: str = "warn") -> None:
        self.k, self.h, self.baseline_s, self.min_sigma, self.severity = k, h, baseline_s, min_sigma, severity
        self.name = f"cusum(k={k:g},h={h:g})"

    def run(self, t: list[float], r: list[float], signal: str = "") -> list[Alarm]:
        if len(t) < 10:
            return []
        t0 = t[0]
        base = [v for x, v in zip(t, r) if x - t0 <= self.baseline_s]
        if len(base) < 5:
            base = r[:max(5, len(r) // 10)]
        mu = sum(base) / len(base)
        sigma = max(math.sqrt(sum((v - mu) ** 2 for v in base) / len(base)), self.min_sigma)
        out, gp, gn, start = [], 0.0, 0.0, None
        for x, v in zip(t, r):
            if x - t0 <= self.baseline_s:
                continue                              # the baseline window defines "normal"; it is not tested
            z = (v - mu) / sigma
            gp, gn = max(0.0, gp + z - self.k), max(0.0, gn - z - self.k)
            if (gp > self.h or gn > self.h):
                direction = "up" if gp > self.h else "down"
                out.append(Alarm(self.name, signal, x, x, max(gp, gn), self.severity,
                                 f"shift {direction}, baseline {mu:.3g}, sigma {sigma:.3g}"))
                gp = gn = 0.0                         # restart so a persistent shift alarms again only after re-accumulating
        return out


class WindowRms:
    def __init__(self, window_s: float, limit: float, severity: str = "warn") -> None:
        self.window_s, self.limit, self.severity = window_s, limit, severity
        self.name = f"rms{window_s:g}s>{limit:g}"

    def run(self, t: list[float], r: list[float], signal: str = "") -> list[Alarm]:
        out, win, ssum, start, peak = [], deque(), 0.0, None, 0.0
        for x, v in zip(t, r):
            win.append((x, v * v))
            ssum += v * v
            while win and x - win[0][0] > self.window_s:
                ssum -= win.popleft()[1]
            if x - t[0] < self.window_s:
                continue
            rms = math.sqrt(max(ssum, 0.0) / len(win))
            if rms > self.limit:
                if start is None:
                    start, peak = x, 0.0
                peak, last = max(peak, rms), x
            elif start is not None:
                out.append(Alarm(self.name, signal, start, last, peak, self.severity))
                start = None
        if start is not None:
            out.append(Alarm(self.name, signal, start, last, peak, self.severity))
        return out


def detect(res: Residual, *detectors) -> list[Alarm]:
    alarms = []
    for d in detectors:
        alarms.extend(d.run(res.t, res.r, res.name))
    return sorted(alarms, key=lambda a: a.t_start)


class EventLog:
    """Collects alarms from many signals; merges alarms of the same detector and signal that are closer than ``gap_s``."""

    def __init__(self, gap_s: float = 1.0) -> None:
        self.gap_s = gap_s
        self.alarms: list[Alarm] = []

    def add(self, alarms: list[Alarm]) -> None:
        for a in sorted(alarms, key=lambda a: a.t_start):
            prev = next((p for p in reversed(self.alarms) if p.detector == a.detector and p.signal == a.signal), None)
            if prev is not None and a.t_start - prev.t_end <= self.gap_s:
                prev.t_end, prev.peak = max(prev.t_end, a.t_end), max(prev.peak, a.peak)
            else:
                self.alarms.append(Alarm(**asdict(a)))

    def first(self, signal: str | None = None) -> Alarm | None:
        c = [a for a in self.alarms if signal is None or a.signal == signal]
        return min(c, key=lambda a: a.t_start) if c else None

    def events(self) -> list[dict]:
        return [a.to_event() for a in sorted(self.alarms, key=lambda a: a.t_start)]

    def summary(self) -> str:
        if not self.alarms:
            return "no divergence detected"
        return "\n".join(f"{a.t_start:9.2f}-{a.t_end:9.2f}s  {a.severity:5s}  {a.signal}: {a.detector} peak {a.peak:.3g} {a.detail}"
                         for a in sorted(self.alarms, key=lambda a: a.t_start))
