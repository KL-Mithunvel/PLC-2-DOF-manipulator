"""Fit the motor torque constant from a recorded run that contains measured sensor current.

    python -m tools.fit_motor_params logs/run_xxx.jsonl [--write]

Model per axis:   I_meas[mA] = a * |tau| / N  +  I0     (tau = output torque N.m from the twin, N = gear ratio)
Then  eta*kt = 1000 / a   -> kt = eta*kt / eta  (gear efficiency eta is kept at the configured value, so the
product is what is really identified; if you know eta from elsewhere, set it first).  I0 = idle current.
With --write the result goes to twin_config.json as base.kt / shoulder.kt.
"""
from __future__ import annotations

import argparse
import json
import os

from twin.config import OVERRIDE_FILE, TwinCfg


def linfit(x: list[float], y: list[float]) -> tuple[float, float, float]:
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    a = sxy / sxx
    b = my - a * mx
    ss_res = sum((yy - (a * xx + b)) ** 2 for xx, yy in zip(x, y))
    ss_tot = sum((yy - my) ** 2 for yy in y) or 1.0
    return a, b, 1 - ss_res / ss_tot


def _smooth(v: list[float], n: int) -> list[float]:
    """Trailing moving average over ``n`` samples."""
    if n <= 1:
        return v
    out, acc = [], 0.0
    for i, x in enumerate(v):
        acc += x
        if i >= n:
            acc -= v[i - n]
        out.append(acc / min(i + 1, n))
    return out


def fit_log(frames: list[dict], cfg: TwinCfg | None = None, smooth: int = 1) -> dict:
    """``smooth``: average both the torque and the measured current over this many consecutive frames before fitting. Use it whenever
    the measurement is not simultaneous with the torque (a power meter that updates a few times a second, a sensor with its own
    averaging): the torque ripples much faster than the meter, and regressing a smoothed signal on an instantaneous one biases the slope."""
    cfg = cfg or TwinCfg()
    out = {}
    for key, ax in (("base", cfg.base), ("shoulder", cfg.shoulder)):
        x, y = [], []
        for f in frames:
            s = (f.get("sensors") or {}).get(key)
            if s and key in f and "tau" in f[key]:
                x.append(abs(f[key]["tau"]) / ax.ratio)
                y.append(s["mA"])
        x, y = _smooth(x, smooth), _smooth(y, smooth)
        if len(x) < 20 or max(x) - min(x) < 1e-6:
            out[key] = {"error": f"not enough varied data ({len(x)} samples)"}
            continue
        a, b, r2 = linfit(x, y)
        eta_kt = 1000.0 / a
        out[key] = {"kt": round(eta_kt / ax.eta, 5), "idle_mA": round(b, 1), "r2": round(r2, 4), "samples": len(x),
                    "was_kt": ax.kt}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--smooth", type=int, default=1, help="average torque and current over this many frames (needed for slow meters)")
    a = ap.parse_args()
    from twin.sources import load_snapshots          # old .jsonl logs and bag files
    frames = load_snapshots(a.log)
    res = fit_log(frames, smooth=a.smooth)
    print(json.dumps(res, indent=1))
    if a.write:
        old = json.load(open(OVERRIDE_FILE)) if os.path.exists(OVERRIDE_FILE) else {}
        for k, v in res.items():
            if "kt" in v:
                old[f"{k}.kt"] = v["kt"]
        with open(OVERRIDE_FILE, "w") as fh:
            json.dump(old, fh, indent=1)
        print("written", OVERRIDE_FILE)


if __name__ == "__main__":
    main()
