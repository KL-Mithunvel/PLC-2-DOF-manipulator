"""Compare two recorded runs (e.g. twin vs live PLC, twin vs mocap): time alignment + per-axis and tip error.

    python -m tools.compare_runs logs/sim.jsonl logs/mocap.jsonl [--max-lag 10] [--no-align]

B is shifted in time to best match A (minimum squared error of the shoulder angle, searched over +-max-lag seconds),
so clocks need not be synchronised.  Reports the lag found and RMS / max error of base angle, shoulder angle and tip position.
"""
from __future__ import annotations

import argparse
import json
import math


def load(path: str) -> list[dict]:
    return [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]


def series(frames: list[dict]):
    t = [f["t"] for f in frames]
    return t, [f["base"]["deg"] for f in frames], [f["shoulder"]["deg"] for f in frames], [f["geom"]["tip"] for f in frames]


def interp(ts: list[float], vs: list[float], t: float) -> float | None:
    if t < ts[0] or t > ts[-1]:
        return None
    lo, hi = 0, len(ts) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if ts[mid] <= t:
            lo = mid
        else:
            hi = mid
    if ts[hi] == ts[lo]:
        return vs[lo]
    k = (t - ts[lo]) / (ts[hi] - ts[lo])
    return vs[lo] + k * (vs[hi] - vs[lo])


def _mse(ta, sa, tb, sb, lag: float, step: float = 0.1) -> tuple[float, int]:
    err, n, t = 0.0, 0, ta[0]
    while t <= ta[-1]:
        a = interp(ta, sa, t)
        b = interp(tb, sb, t - lag)
        if a is not None and b is not None:
            err += (a - b) ** 2
            n += 1
        t += step
    return (err / n if n else float("inf")), n


def find_lag(ta, sa, tb, sb, max_lag: float = 10.0) -> float:
    """lag such that B(t - lag) ~ A(t)  (positive = B is delayed)."""
    best = (float("inf"), 0.0)
    lag = -max_lag
    while lag <= max_lag:
        m, n = _mse(ta, sa, tb, sb, lag, 0.2)
        if n > 20 and m < best[0]:
            best = (m, lag)
        lag += 0.1
    lag0 = best[1]
    for k in range(-20, 21):                      # refine to 5 ms
        lag = lag0 + k * 0.005
        m, n = _mse(ta, sa, tb, sb, lag, 0.05)
        if n > 20 and m < best[0]:
            best = (m, lag)
    return best[1]


def compare(a: list[dict], b: list[dict], max_lag: float = 10.0, align: bool = True) -> dict:
    ta, ba, sa, tipa = series(a)
    tb, bb, sb, tipb = series(b)
    lag = find_lag(ta, sa, tb, sb, max_lag) if align else 0.0
    eb, es, et = [], [], []
    t = ta[0]
    while t <= ta[-1]:
        vb = interp(tb, bb, t - lag)
        vs = interp(tb, sb, t - lag)
        if vb is not None and vs is not None:
            eb.append(interp(ta, ba, t) - vb)
            es.append(interp(ta, sa, t) - vs)
            tip = [interp(tb, [p[k] for p in tipb], t - lag) for k in range(3)]
            ref = [interp(ta, [p[k] for p in tipa], t) for k in range(3)]
            et.append(math.dist(tip, ref) * 1000)
        t += 0.05
    if not eb:
        raise ValueError("runs do not overlap in time after alignment")
    rms = lambda v: math.sqrt(sum(x * x for x in v) / len(v))
    return {"lag_s": lag, "samples": len(eb),
            "base_deg": {"rms": rms(eb), "max": max(abs(x) for x in eb), "bias": sum(eb) / len(eb)},
            "shoulder_deg": {"rms": rms(es), "max": max(abs(x) for x in es), "bias": sum(es) / len(es)},
            "tip_mm": {"rms": rms(et), "max": max(et)}}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--max-lag", type=float, default=10.0)
    ap.add_argument("--no-align", action="store_true")
    x = ap.parse_args()
    print(json.dumps(compare(load(x.a), load(x.b), x.max_lag, not x.no_align), indent=1))


if __name__ == "__main__":
    main()
