"""Pipeline diagnostics for a polled data source: latency, period, jitter, error and reconnect counts, data age.

Standard library only. ``PollStats`` is fed by the reader; ``summary()`` is what the GUI shows and what is written to the
``diag`` bag topic. All times are ``time.monotonic()`` seconds unless a name ends in ``_ms``.
"""
from __future__ import annotations

import math
import time
from collections import deque


class Rolling:
    """Last ``n`` samples with mean / percentile / max / standard deviation."""

    def __init__(self, n: int = 200) -> None:
        self.v: deque[float] = deque(maxlen=n)
        self.total = 0

    def add(self, x: float) -> None:
        self.v.append(float(x))
        self.total += 1

    def summary(self) -> dict:
        v = sorted(self.v)
        if not v:
            return {"n": 0}
        n = len(v)
        mean = sum(v) / n
        std = math.sqrt(sum((x - mean) ** 2 for x in v) / n)
        pick = lambda q: v[min(n - 1, int(q * n))]          # noqa: E731
        return {"n": n, "mean": round(mean, 3), "p50": round(pick(0.5), 3), "p95": round(pick(0.95), 3),
                "max": round(v[-1], 3), "min": round(v[0], 3), "std": round(std, 3)}


class PollStats:
    def __init__(self, window: int = 200) -> None:
        self.window = window
        self.block: dict[str, Rolling] = {}       # one request: round-trip ms
        self.cycle: dict[str, Rolling] = {}       # one group poll: total ms
        self.period: dict[str, Rolling] = {}      # start-to-start ms of a group
        self._last_start: dict[str, float] = {}
        self.polls = 0
        self.errors = 0
        self.reconnects = 0
        self.last_error = ""
        self.last_ok = None                        # monotonic time of the last good poll
        self.started = time.monotonic()

    def _r(self, d: dict, key: str) -> Rolling:
        r = d.get(key)
        if r is None:
            r = d[key] = Rolling(self.window)
        return r

    def record_block(self, key: str, ms: float) -> None:
        self._r(self.block, key).add(ms)

    def record_cycle(self, group: str, t_start: float, ms: float) -> None:
        self._r(self.cycle, group).add(ms)
        last = self._last_start.get(group)
        if last is not None:
            self._r(self.period, group).add((t_start - last) * 1000.0)
        self._last_start[group] = t_start
        self.polls += 1
        self.last_ok = t_start + ms / 1000.0

    def error(self, msg: str) -> None:
        self.errors += 1
        self.last_error = msg

    def reconnect(self) -> None:
        self.reconnects += 1

    def summary(self, now: float | None = None) -> dict:
        now = time.monotonic() if now is None else now
        groups = {}
        for g, c in self.cycle.items():
            p = self.period.get(g)
            groups[g] = {"cycle_ms": c.summary(), "period_ms": p.summary() if p else {"n": 0},
                         "jitter_ms": (p.summary().get("std") if p else None),
                         "rate_hz": (round(1000.0 / p.summary()["mean"], 2) if p and p.summary().get("mean") else None)}
        return {"polls": self.polls, "errors": self.errors, "reconnects": self.reconnects, "last_error": self.last_error,
                "age_s": None if self.last_ok is None else round(now - self.last_ok, 3),
                "uptime_s": round(now - self.started, 1),
                "groups": groups, "blocks": {k: r.summary() for k, r in self.block.items()}}
