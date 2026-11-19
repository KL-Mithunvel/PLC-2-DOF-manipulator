"""Camera intrinsic calibration from chessboard photos.

    python -m mocap.calibrate --images "calib/*.jpg" --pattern 9x6 --square 0.03 --out mocap/camera.json

``--pattern`` = number of INNER corners (columns x rows); ``--square`` = square side in metres (measure the printed board).
Take 15-30 photos with the board at different positions, tilts and distances covering the whole image.
Reports the RMS reprojection error in pixels (under about 0.5 px is good).
"""
from __future__ import annotations

import argparse
import glob

import cv2
import numpy as np

from .tracker import Camera


def calibrate(images: list[np.ndarray], pattern=(9, 6), square: float = 0.03) -> tuple[Camera, float, int]:
    objp = np.zeros((pattern[0] * pattern[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:pattern[0], 0:pattern[1]].T.reshape(-1, 2) * square
    obj, img = [], []
    size = None
    for im in images:
        gray = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY) if im.ndim == 3 else im
        size = (gray.shape[1], gray.shape[0])
        ok, corners = cv2.findChessboardCorners(gray, pattern, cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE)
        if not ok:
            continue
        corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.001))
        obj.append(objp)
        img.append(corners)
    if len(obj) < 5:
        raise ValueError(f"chessboard found in only {len(obj)} images (need at least 5, ideally 15+)")
    rms, K, dist, _, _ = cv2.calibrateCamera(obj, img, size, None, None)
    return Camera(K, dist.ravel(), size), float(rms), len(obj)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--images", required=True, help="glob, e.g. calib/*.jpg")
    ap.add_argument("--pattern", default="9x6")
    ap.add_argument("--square", type=float, default=0.03)
    ap.add_argument("--out", default="mocap/camera.json")
    a = ap.parse_args()
    cols, rows = (int(x) for x in a.pattern.split("x"))
    imgs = [cv2.imread(p) for p in sorted(glob.glob(a.images))]
    cam, rms, n = calibrate([i for i in imgs if i is not None], (cols, rows), a.square)
    cam.save(a.out, rms)
    print(f"{n} usable images, RMS reprojection error {rms:.3f} px, fx={cam.K[0, 0]:.1f} fy={cam.K[1, 1]:.1f} cx={cam.K[0, 2]:.1f} cy={cam.K[1, 2]:.1f}")
    print("saved", a.out)


if __name__ == "__main__":
    main()
