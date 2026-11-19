"""Camera placement check: how well can a camera at a given position see the link tags over the base yaw range?

    python -m mocap.placement --camera -0.6 0.6 0.6 --yaw-range 0 90

For every yaw and a few pitch values it reports the viewing angle of the best link tag (angle between the tag normal and
the line to the camera; below ~60 degrees is reliable, above 75 degrees the tag is practically edge-on) and the apparent size
in pixels for a given focal length.  Also tries a grid of candidate positions and prints the best.
"""
from __future__ import annotations

import argparse
import math

import numpy as np

from .geometry import T, default_layout, link_rotation


def tag_view(cam_pos, yaw_deg: float, pitch_deg: float, layout=None, h: float = 0.17, focal_px: float = 1000.0):
    layout = layout or default_layout(h)
    T_wl = T(link_rotation(math.radians(yaw_deg), math.radians(pitch_deg)), [0, 0, h])
    best = (180.0, None, 0.0)
    for mid, m in layout.items():
        if m.parent != "link":
            continue
        Twm = T_wl @ m.T_parent_marker
        to_cam = np.array(cam_pos) - Twm[:3, 3]
        dist = np.linalg.norm(to_cam)
        ang = math.degrees(math.acos(max(-1, min(1, np.dot(Twm[:3, 2], to_cam) / dist))))
        if ang < best[0]:
            best = (ang, mid, focal_px * m.size / dist * math.cos(math.radians(min(ang, 89))))
    return best


def worst_case(cam_pos, yaw_range=(0, 90), pitch_values=(0, 45, 90), h: float = 0.17):
    worst = 0.0
    for yaw in np.linspace(yaw_range[0], yaw_range[1], 19):
        for p in pitch_values:
            worst = max(worst, tag_view(cam_pos, yaw, p, h=h)[0])
    return worst


def search(yaw_range=(0, 90), z: float = 0.6, radius: float = 0.8):
    cands = []
    for az in range(0, 360, 15):
        pos = (radius * math.cos(math.radians(az)), radius * math.sin(math.radians(az)), z)
        cands.append((worst_case(pos, yaw_range), az, pos))
    return sorted(cands)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--camera", nargs=3, type=float, metavar=("X", "Y", "Z"))
    ap.add_argument("--yaw-range", nargs=2, type=float, default=[0, 90])
    ap.add_argument("--focal-px", type=float, default=1000)
    a = ap.parse_args()
    yr = tuple(a.yaw_range)
    if a.camera:
        print(f"camera at {a.camera}: yaw  pitch  best-tag  view-angle  apparent-size(px)")
        for yaw in np.linspace(yr[0], yr[1], 7):
            for p in (0, 45, 90):
                ang, mid, px = tag_view(a.camera, yaw, p, focal_px=a.focal_px)
                print(f"  {yaw:5.0f} {p:5.0f}   tag {mid}   {ang:6.1f} deg   {px:5.1f}")
        print("worst-case view angle:", round(worst_case(a.camera, yr), 1), "deg")
    print("best camera azimuths (radius 0.8 m, height 0.6 m), worst-case view angle:")
    for w, az, pos in search(yr)[:4]:
        print(f"  azimuth {az:3d} deg  position ({pos[0]:+.2f}, {pos[1]:+.2f}, {pos[2]:.2f})  worst {w:.1f} deg")


if __name__ == "__main__":
    main()
