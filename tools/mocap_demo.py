"""End-to-end mocap demo without hardware: simulated run -> synthetic camera video -> tracker -> comparison.

    python -m tools.mocap_demo [--seconds 25] [--video demo.mp4] [--noise 2] [--resolution 1920x1080]

Runs the twin (3 auto cycles), renders what a camera at azimuth 135 deg would see, tracks the tags, writes
logs/demo_sim.jsonl and logs/demo_mocap.jsonl, and prints the tracking error (what you can expect from a real camera
of that resolution, minus lens distortion, lighting and mounting errors).
"""
from __future__ import annotations

import argparse
import json
import math
import os

import cv2
import numpy as np

from mocap.geometry import look_at
from mocap.source import MocapSource
from mocap.synth import render
from mocap.tracker import Camera
from tools.compare_runs import compare
from twin.config import TwinCfg
from twin.sim import Twin
from twin.sources import LOG_DIR


def run_demo(seconds: float = 25.0, noise: float = 2.0, resolution=(1920, 1080), video: str | None = None,
             out_dir: str = LOG_DIR, lag_s: float = 0.0) -> dict:
    cfg = TwinCfg()
    f = 1650.0 * resolution[0] / 1920
    cam = Camera(np.array([[f, 0, resolution[0] / 2], [0, f, resolution[1] / 2], [0, 0, 1]]), np.zeros(5), resolution)
    T_wc = look_at((-0.5, 0.7, 0.6), (0.1, 0.05, 0.25))
    twin = Twin(cfg)
    for _ in range(800):
        twin.tick()
    twin.command({"type": "button", "tag": "START", "down": True})
    src = MocapSource(lambda stop: iter(()), cam, cfg)
    vw = cv2.VideoWriter(video, cv2.VideoWriter_fourcc(*"mp4v"), 25, resolution) if video else None
    sim_frames, mocap_frames = [], []
    os.makedirs(out_dir, exist_ok=True)
    for i in range(int(seconds / 0.005)):
        twin.tick()
        if i == 80:
            twin.command({"type": "button", "tag": "START", "down": False})
        if i % 8:                                           # 25 fps
            continue
        snap = twin.snapshot()
        sim_frames.append({k: snap[k] for k in ("schema", "source", "t", "base", "shoulder", "geom", "io")})
        img = render(cam, T_wc, math.radians(snap["base"]["deg"]), math.radians(snap["shoulder"]["deg"]), noise=noise, seed=i)
        if vw:
            vw.write(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR))
        if src.process(twin.t + lag_s, img):
            ms = src.snapshot()
            mocap_frames.append({k: ms[k] for k in ("schema", "source", "t", "base", "shoulder", "geom", "io")})
    if vw:
        vw.release()
    for name, frames in (("demo_sim", sim_frames), ("demo_mocap", mocap_frames)):
        with open(os.path.join(out_dir, name + ".jsonl"), "w") as fh:
            fh.write("\n".join(json.dumps(x) for x in frames) + "\n")
    res = compare(sim_frames, mocap_frames, align=lag_s != 0.0)
    res["frames"] = len(sim_frames)
    res["tracked"] = len(mocap_frames)
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seconds", type=float, default=25)
    ap.add_argument("--noise", type=float, default=2.0)
    ap.add_argument("--resolution", default="1920x1080")
    ap.add_argument("--video")
    a = ap.parse_args()
    w, h = (int(x) for x in a.resolution.split("x"))
    print(json.dumps(run_demo(a.seconds, a.noise, (w, h), a.video), indent=1))


if __name__ == "__main__":
    main()
