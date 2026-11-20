"""Time alignment of two signals that were recorded with clocks (or pipelines) that disagree.

Convention: a positive ``lag`` means **b is later than a**: ``b(t) ~ a(t - lag)``, so the same physical moment is ``a(t)`` and
``b(t + lag)``. ``residual(real, twin, lag)`` therefore compares ``real(t)`` with ``twin(t + lag)``.
(tools/compare_runs.py uses the opposite sign: its lag is the amount B must be moved back to match A.)

Two methods:
* ``estimate_lag``        cross-correlation of the two analog signals on a uniform grid, refined below the grid step.
* ``estimate_lag_edges``  matches rising edges of two binary signals (a PLC bit and the twin's bit); very robust, and also gives the
                          per-edge delays, which are themselves a measurement (``edge_delays``).
``lag_drift`` repeats the estimate in windows to see a clock that runs at a different speed.
Standard library only.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .signals import Signal, rising_edges


@dataclass
class LagResult:
    lag: float            # seconds, b is later than a by this much
    score: float          # normalised correlation in [-1, 1] at the best lag (1 = identical shape)
    n: int                # samples used at the best lag
    method: str = "xcorr"


def _grid(sig: Signal, t0: float, dt: float, n: int) -> list[float | None]:
    return [sig.at(t0 + i * dt) for i in range(n)]


def _pearson(x: list[float | None], y: list[float | None]) -> tuple[float, int]:
    xs, ys = [], []
    for a, b in zip(x, y):
        if a is not None and b is not None:
            xs.append(a)
            ys.append(b)
    n = len(xs)
    if n < 5:
        return -2.0, n
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((a - mx) ** 2 for a in xs)
    syy = sum((b - my) ** 2 for b in ys)
    if sxx < 1e-12 or syy < 1e-12:
        return 0.0, n
    sxy = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    return sxy / math.sqrt(sxx * syy), n


def estimate_lag(a: Signal, b: Signal, max_lag: float = 5.0, dt: float = 0.05, min_overlap: float = 0.5) -> LagResult:
    """Lag of ``b`` relative to ``a`` (positive = b later) by maximising the correlation of ``a(t)`` and ``b(t + lag)``.
    ``min_overlap``: fraction of ``a``'s length that must overlap with the shifted ``b`` (avoids chance matches at the extremes)."""
    if len(a) < 5 or len(b) < 5:
        raise ValueError("need at least 5 samples in each signal")
    n = int((a.t1 - a.t0) / dt) + 1
    ga = _grid(a, a.t0, dt, n)
    steps = int(round(max_lag / dt))
    # b resampled on the same grid for every integer shift: b(t0 + (i - k) dt)
    best = (-3.0, 0, 0)
    scores: dict[int, float] = {}
    big = [b.at(a.t0 + j * dt) for j in range(-steps, n + steps)]       # b on the grid once; every shift is a slice
    for k in range(-steps, steps + 1):
        gb = big[steps + k: steps + k + n]                               # b(t0 + (i + k) dt)
        r, cnt = _pearson(ga, gb)
        if cnt < min_overlap * n:
            continue
        scores[k] = r
        if r > best[0]:
            best = (r, k, cnt)
    if best[0] < -1.5:
        raise ValueError("signals do not overlap enough for any lag in the search range")
    r, k, cnt = best
    lag = k * dt
    if k - 1 in scores and k + 1 in scores:                    # parabolic refinement through the three best points
        y0, y1, y2 = scores[k - 1], scores[k], scores[k + 1]
        den = y0 - 2 * y1 + y2
        if den < -1e-12:
            lag += 0.5 * (y0 - y2) / den * dt
    return LagResult(lag, r, cnt)


def estimate_lag_edges(a: Signal, b: Signal, max_lag: float = 5.0, level: float = 0.5) -> LagResult:
    """Median delay between each rising edge of ``a`` and the nearest later-or-equal edge of ``b`` (within ``max_lag`` either way).
    ``score`` is the fraction of ``a``'s edges that found a partner."""
    ea, eb = rising_edges(a, level), rising_edges(b, level)
    if not ea or not eb:
        raise ValueError("no rising edges in one of the signals")
    d = edge_delays(ea, eb, max_lag)
    if not d:
        raise ValueError("no edge of a has a partner in b within max_lag")
    d.sort()
    return LagResult(d[len(d) // 2], len(d) / len(ea), len(d), "edges")


def edge_delays(ea: list[float], eb: list[float], max_lag: float = 5.0) -> list[float]:
    """For each edge time in ``ea`` the signed delay to the nearest edge in ``eb`` (None-free: edges without a partner within
    ``max_lag`` are left out). Matching is one-to-one."""
    out, used = [], set()
    for t in ea:
        best = None
        for j, u in enumerate(eb):
            if j in used:
                continue
            if abs(u - t) <= max_lag and (best is None or abs(u - t) < abs(eb[best] - t)):
                best = j
        if best is not None:
            used.add(best)
            out.append(eb[best] - t)
    return out


def lag_drift(a: Signal, b: Signal, window_s: float = 60.0, step_s: float = 30.0, max_lag: float = 2.0, dt: float = 0.05) -> dict:
    """Lag per window and a straight-line fit lag(t) = lag0 + slope * t. ``slope`` (s/s, times 1e6 = ppm) is the clock-rate difference."""
    pts = []
    t = a.t0
    while t + window_s <= a.t1:
        w = a.window(t, t + window_s)
        try:
            r = estimate_lag(w, b, max_lag=max_lag, dt=dt)
            if r.score > 0.5:
                pts.append((t + window_s / 2, r.lag))
        except ValueError:
            pass
        t += step_s
    if len(pts) < 3:
        raise ValueError("too few good windows to fit a drift")
    n = len(pts)
    mt, ml = sum(p[0] for p in pts) / n, sum(p[1] for p in pts) / n
    sxx = sum((p[0] - mt) ** 2 for p in pts)
    slope = sum((p[0] - mt) * (p[1] - ml) for p in pts) / sxx if sxx else 0.0
    return {"windows": pts, "lag0": ml - slope * mt, "slope": slope, "ppm": slope * 1e6}
