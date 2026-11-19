"""Fake motor-sensor MCU for testing: reads the twin over HTTP and sends S,... lines over UDP.

    python -m tools.sim_sensors --twin http://127.0.0.1:8765 --udp 127.0.0.1:9100 [--kt-scale 1.3] [--hz 50]

The "measured" current is the twin's torque converted with a *different* torque constant (``--kt-scale``) plus
noise, so the calibration fit (tools/fit_motor_params.py) has something real to recover.
"""
from __future__ import annotations

import argparse
import json
import random
import socket
import time
import urllib.request


def measured_current_ma(axis: dict, ratio: float, eta: float, kt: float, kt_scale: float, noise_ma: float, idle_ma: float) -> float:
    return abs(axis["tau"]) / (ratio * eta * kt * kt_scale) * 1000 + idle_ma + random.gauss(0, noise_ma)


def voltage_mv(current_ma: float, v_supply: float = 24.0, r_ohm: float = 0.15) -> float:
    return (v_supply - current_ma / 1000 * r_ohm) * 1000          # supply sag under load


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--twin", default="http://127.0.0.1:8765")
    ap.add_argument("--udp", default="127.0.0.1:9100")
    ap.add_argument("--hz", type=float, default=50)
    ap.add_argument("--kt-scale", type=float, default=1.3)
    ap.add_argument("--noise-ma", type=float, default=40)
    a = ap.parse_args()
    host, port = a.udp.split(":")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    from twin.config import TwinCfg
    cfg = TwinCfg()
    t0 = time.time()
    while True:
        s = json.loads(urllib.request.urlopen(a.twin + "/api/state", timeout=2).read())
        ms = int((time.time() - t0) * 1000)
        for ch, (key, ax) in enumerate((("base", cfg.base), ("shoulder", cfg.shoulder))):
            i = measured_current_ma(s[key], ax.ratio, ax.eta, ax.kt, a.kt_scale, a.noise_ma, 60)
            sock.sendto(f"S,{ms},{ch},{i:.0f},{voltage_mv(i):.0f}\n".encode(), (host, int(port)))
        time.sleep(1 / a.hz)


if __name__ == "__main__":
    main()
