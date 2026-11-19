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


def fit_log(frames: list[dict], cfg: TwinCfg | None = None) -> dict:
    cfg = cfg or TwinCfg()
    out = {}
    for key, ax in (("base", cfg.base), ("shoulder", cfg.shoulder)):
        x, y = [], []
        for f in frames:
            s = (f.get("sensors") or {}).get(key)
            if s and key in f and "tau" in f[key]:
                x.append(abs(f[key]["tau"]) / ax.ratio)
                y.append(s["mA"])
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
    a = ap.parse_args()
    frames = [json.loads(line) for line in open(a.log, encoding="utf-8") if line.strip()]
    res = fit_log(frames)
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
