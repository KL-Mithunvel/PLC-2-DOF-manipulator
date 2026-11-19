"""Fit the twin to the real machine's cycle time.

    python -m tools.calibrate_cycle --real-time 29.5 --cycles 3 [--fit profile_rpm|timer_base_ms] [--payload 5] [--write]

``--real-time`` = seconds from pressing START to the end of the last cycle on the real arm (e.g. the HMI cycle timer).
Fits ONE parameter by bisection (the cycle time is monotonic in both):
  profile_rpm    drive profile speed (object 6081) for both axes, used when PDO 60FF = 0   [default]
  timer_base_ms  KincoBuilder time base of T1..T26 (10 ms assumed): scales the dwell times
With ``--write`` the result is stored in twin_config.json (read by every Twin).
"""
from __future__ import annotations

import argparse
import json
import os

from twin.config import OVERRIDE_FILE, TwinCfg, apply_overrides
from twin.sim import Twin


def simulate_run(overrides: dict | None = None, cycles: int = 3, payload: float = 5.0, max_s: float = 300.0) -> float:
    """Seconds from START to auto-complete (%M30.2) in the twin."""
    cfg = apply_overrides(TwinCfg(), overrides or {})
    cfg.arm.payload = payload
    t = Twin(cfg)
    t.plc.mem.write("VW2036", cycles)
    for _ in range(int(4 / 0.005)):
        t.tick()
    t.command({"type": "button", "tag": "START", "down": True})
    start = t.t
    released = False
    for _ in range(int(max_s / 0.005)):
        t.tick()
        # the ladder only enables the drives while M30.0 is held for the enable delay (T2/T3), so hold START
        # until both drives are enabled (controlword 47), like an operator would
        if not released and t.plc.mem.read("M30.1") and t.arm.base.enabled and t.arm.shoulder.enabled:
            t.command({"type": "button", "tag": "START", "down": False})
            released = True
        if t.plc.mem.read("M30.2"):
            return t.t - start
        if not released and t.t - start > 10:
            return float("inf")                  # never enabled: timers too slow for this START hold
    return float("inf")


def fit(real_time: float, cycles: int = 3, param: str = "profile_rpm", payload: float = 5.0, tol: float = 0.01) -> dict:
    if param == "profile_rpm":
        lo, hi = 30.0, 1500.0                      # more rpm -> shorter cycle
        mk = lambda v: {"base.profile_rpm": v, "shoulder.profile_rpm": v}
        shorter_when_higher = True
    elif param == "timer_base_ms":
        lo, hi = 1.0, 200.0                        # larger base -> longer dwell -> longer cycle
        mk = lambda v: {"timer_base_ms": v}
        shorter_when_higher = False
    else:
        raise SystemExit(f"unknown parameter {param}")
    best = None
    for _ in range(14):
        mid = (lo + hi) / 2
        t = simulate_run(mk(mid), cycles, payload)
        best = (mid, t)
        if abs(t - real_time) / real_time < tol:
            break
        too_long = t > real_time
        if too_long == shorter_when_higher:
            lo = mid
        else:
            hi = mid
    value, achieved = best
    return {"param": param, "value": round(value, 2), "simulated_s": round(achieved, 2), "target_s": real_time,
            "overrides": mk(round(value, 2))}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--real-time", type=float, required=True)
    ap.add_argument("--cycles", type=int, default=3)
    ap.add_argument("--fit", default="profile_rpm", choices=["profile_rpm", "timer_base_ms"])
    ap.add_argument("--payload", type=float, default=5.0)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    base_t = simulate_run({}, a.cycles, a.payload)
    print(f"current twin: {base_t:.2f} s for {a.cycles} cycles; real: {a.real_time:.2f} s")
    res = fit(a.real_time, a.cycles, a.fit, a.payload)
    print(json.dumps(res, indent=1))
    if a.write:
        old = json.load(open(OVERRIDE_FILE)) if os.path.exists(OVERRIDE_FILE) else {}
        old.update(res["overrides"])
        with open(OVERRIDE_FILE, "w") as fh:
            json.dump(old, fh, indent=1)
        print("written", OVERRIDE_FILE)


if __name__ == "__main__":
    main()
