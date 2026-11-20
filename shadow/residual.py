"""Residuals: ``real(t) - twin(t + lag)`` (lag > 0 = twin is later, see align.py) on a common uniform time grid, with summary statistics.

For binary signals (PLC bits) the residual is 0 where both agree and +-1 where they differ; ``mismatch_intervals`` lists the
time spans of disagreement, which is the useful output for ladder conformance (stage 5).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .signals import Signal


@dataclass
class Residual:
    name: str
    t: list[float]
    r: list[float]
    unit: str = ""
    kind: str = "analog"
    lag: float = 0.0

    def __len__(self) -> int:
        return len(self.t)

    def stats(self) -> dict:
        n = len(self.r)
        if not n:
            return {"n": 0}
        mean = sum(self.r) / n
        rms = math.sqrt(sum(x * x for x in self.r) / n)
        std = math.sqrt(sum((x - mean) ** 2 for x in self.r) / n)
        i = max(range(n), key=lambda k: abs(self.r[k]))
        return {"n": n, "bias": mean, "rms": rms, "std": std, "max_abs": abs(self.r[i]), "t_max": self.t[i], "lag": self.lag}


def residual(real: Signal, twin: Signal, lag: float = 0.0, dt: float = 0.05, name: str | None = None, t_from: float | None = None,
             t_to: float | None = None) -> Residual:
    """Grid step ``dt`` over the overlap of ``real`` and the lag-corrected ``twin``. Samples where either is undefined are skipped."""
    lo = max(real.t0, twin.t0 - lag, t_from if t_from is not None else -math.inf)
    hi = min(real.t1, twin.t1 - lag, t_to if t_to is not None else math.inf)
    if hi <= lo:
        raise ValueError("no overlap between the two signals after applying the lag")
    n = int((hi - lo) / dt) + 1
    t, r = [], []
    for i in range(n):
        x = lo + i * dt
        a, b = real.at(x), twin.at(x + lag)
        if a is None or b is None:
            continue
        t.append(x)
        r.append(a - b)
    return Residual(name or f"{real.name} - {twin.name}", t, r, real.unit, "binary" if real.kind == "binary" else "analog", lag)


def mismatch_intervals(res: Residual, min_len: float = 0.0, tol: float = 0.5) -> list[tuple[float, float]]:
    """Spans of time where ``|r| > tol`` (for binary residuals: the two bits disagree). Spans shorter than ``min_len`` are dropped,
    which removes disagreement that is only a small timing offset of an edge."""
    spans, start, prev = [], None, None
    for x, v in zip(res.t, res.r):
        bad = abs(v) > tol
        if bad and start is None:
            start = x
        if not bad and start is not None:
            spans.append((start, prev if prev is not None else x))
            start = None
        prev = x
    if start is not None:
        spans.append((start, res.t[-1]))
    return [s for s in spans if s[1] - s[0] >= min_len]


def mismatch_rate(res: Residual, tol: float = 0.5) -> float:
    return sum(1 for v in res.r if abs(v) > tol) / len(res.r) if res.r else 0.0
