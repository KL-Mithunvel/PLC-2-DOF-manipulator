"""Write printable ArUco tags (4x4_50) as PNG files with the white quiet zone included.

    python -m tools.make_tags --size-mm 60 --dpi 300 --out tags

Prints each tag at the exact physical size: print at 100 % scale (no "fit to page") and measure the black square (should be
--size-mm).  Use matte paper/vinyl; glossy or reflective material causes glare under room light.  Mounting (see mocap/geometry.py):
  id 0 flat on the base top face, id 1 on the +y plate and id 3 on the -y plate of Link-1 (outer faces), id 2 on top of the part.
"""
from __future__ import annotations

import argparse
import os

import cv2

from mocap.synth import QUIET


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--size-mm", type=float, default=60.0)
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--ids", type=int, nargs="*", default=[0, 1, 2, 3])
    ap.add_argument("--out", default="tags")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    px = round(a.size_mm / 25.4 * a.dpi)
    d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    for i in a.ids:
        img = cv2.aruco.generateImageMarker(d, i, px)
        pad = round(px * QUIET)
        img = cv2.copyMakeBorder(img, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)
        path = os.path.join(a.out, f"tag_{i}.png")
        cv2.imwrite(path, img)
        print(path, f"{img.shape[1]}x{img.shape[0]} px, black square {a.size_mm} mm at {a.dpi} dpi")


if __name__ == "__main__":
    main()
