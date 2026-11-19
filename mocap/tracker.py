"""ArUco tag tracker: camera image -> base yaw / shoulder pitch (+ part position when its tag is visible).

Chain:  base tag (known world pose)  ->  camera pose in the world
        link tag  (known mounting on Link-1) -> link frame in the world -> (phi, theta)
Every visible link tag gives an independent estimate; they are combined (weighted by the tag's apparent size).
The reprojection of the shoulder axis (link-frame origin vs the known (0,0,h)) is reported as ``resid_mm`` quality.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

import cv2
import numpy as np

from .geometry import Marker, T, angles_from_link_rotation, default_layout, inv, marker_corners


@dataclass
class Camera:
    K: np.ndarray
    dist: np.ndarray = field(default_factory=lambda: np.zeros(5))
    size: tuple = (1280, 720)

    @classmethod
    def load(cls, path: str) -> "Camera":
        d = json.load(open(path))
        return cls(np.array(d["K"]), np.array(d["dist"]), tuple(d["size"]))

    def save(self, path: str, rms: float | None = None) -> None:
        json.dump({"K": self.K.tolist(), "dist": self.dist.ravel().tolist(), "size": list(self.size), "rms_px": rms}, open(path, "w"), indent=1)


@dataclass
class Estimate:
    base_deg: float
    shoulder_deg: float
    tags: list
    resid_mm: float
    cam_pose: np.ndarray
    part_world: list | None = None
    per_tag_deg: dict = field(default_factory=dict)


class Tracker:
    def __init__(self, camera: Camera, layout: dict[int, Marker] | None = None, shoulder_height: float = 0.17,
                 dictionary: int = cv2.aruco.DICT_4X4_50) -> None:
        self.cam = camera
        self.layout = layout or default_layout(shoulder_height)
        self.h = shoulder_height
        self.detector = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(dictionary), cv2.aruco.DetectorParameters())
        self.detector.getDetectorParameters().cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        self.T_wc_last: np.ndarray | None = None

    def _pnp(self, corners: np.ndarray, size: float):
        ok, rvec, tvec = cv2.solvePnP(marker_corners(size), corners.reshape(4, 2).astype(np.float64), self.cam.K, self.cam.dist,
                                      flags=cv2.SOLVEPNP_IPPE_SQUARE)
        if not ok:
            return None
        R, _ = cv2.Rodrigues(rvec)
        return T(R, tvec.ravel())

    def estimate(self, image: np.ndarray) -> Estimate | None:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
        corners, ids, _ = self.detector.detectMarkers(gray)
        if ids is None:
            return None
        poses = {}
        for c, i in zip(corners, ids.ravel()):
            m = self.layout.get(int(i))
            if m is None:
                continue
            Tct = self._pnp(c, m.size)
            if Tct is not None:
                poses[int(i)] = (Tct, float(np.sqrt(cv2.contourArea(c.reshape(4, 2).astype(np.float32)))))
        base = next((poses[i] for i, m in self.layout.items() if m.parent == "world" and i in poses), None)
        if base is None:
            return None
        base_id = next(i for i, m in self.layout.items() if m.parent == "world" and i in poses)
        T_wc = self.layout[base_id].T_parent_marker @ inv(base[0])               # camera pose in the world
        self.T_wc_last = T_wc
        ests, weights, resid, per_tag = [], [], [], {}
        for i, (Tct, w) in poses.items():
            m = self.layout[i]
            if m.parent != "link":
                continue
            T_wl = T_wc @ Tct @ inv(m.T_parent_marker)                           # link frame in the world
            phi, th = angles_from_link_rotation(T_wl[:3, :3])
            ests.append((phi, th))
            weights.append(w)
            per_tag[i] = (math.degrees(phi), math.degrees(th))
            resid.append(float(np.linalg.norm(T_wl[:3, 3] - np.array([0, 0, self.h]))) * 1000)
        if not ests:
            return None
        w = np.array(weights) / sum(weights)
        # average angles on the circle for yaw, linearly for pitch
        phi = math.atan2(sum(wi * math.sin(p) for wi, (p, _) in zip(w, ests)), sum(wi * math.cos(p) for wi, (p, _) in zip(w, ests)))
        th = sum(wi * t for wi, (_, t) in zip(w, ests))
        part = None
        for i, (Tct, _) in poses.items():
            if self.layout.get(i) and self.layout[i].parent == "part":
                part = (T_wc @ Tct)[:3, 3].tolist()
        return Estimate(math.degrees(phi), math.degrees(th), sorted(poses), float(np.mean(resid)), T_wc, part, per_tag)
