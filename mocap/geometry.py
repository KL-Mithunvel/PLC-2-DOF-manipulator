"""Rigid-transform helpers (numpy) and the mocap marker layout.

Conventions: world = the twin's frame (z up, origin on the base axis at table level, yaw 0 = arm towards +x).
A transform T_ab maps points from frame b to frame a (4x4).  Marker frame: origin at the marker centre, x right,
y up in the marker plane (as seen reading the marker), z out of the marker face.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


def T(R: np.ndarray, t) -> np.ndarray:
    m = np.eye(4)
    m[:3, :3] = R
    m[:3, 3] = t
    return m


def inv(Tm: np.ndarray) -> np.ndarray:
    R, t = Tm[:3, :3], Tm[:3, 3]
    return T(R.T, -R.T @ t)


def rot_z(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])


def rot_y(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1.0, 0], [-s, 0, c]])


def link_rotation(phi: float, theta: float) -> np.ndarray:
    """World orientation of the link frame (z along the arm, y = pitch axis)."""
    return rot_z(phi) @ rot_y(theta)


def angles_from_link_rotation(R: np.ndarray) -> tuple[float, float]:
    """Inverse of link_rotation: (phi, theta).  Uses the pitch axis for yaw, so it is well-defined at theta = 0."""
    x, y, z = R[:, 0], R[:, 1], R[:, 2]
    phi = math.atan2(-y[0], y[1])
    theta = math.atan2(-x[2], z[2])
    return phi, theta


def look_at(pos, target, up=(0, 0, 1.0)) -> np.ndarray:
    """T_wc for an OpenCV camera (x right, y down, z forward) at ``pos`` looking at ``target``."""
    pos, target, up = np.array(pos, float), np.array(target, float), np.array(up, float)
    f = target - pos
    f /= np.linalg.norm(f)
    right = np.cross(f, up)
    right /= np.linalg.norm(right)
    down = np.cross(f, right)
    return T(np.column_stack([right, down, f]), pos)


@dataclass
class Marker:
    id: int
    size: float                    # side length of the black square, metres
    parent: str                    # "world" (base tag), "link" (on Link-1) or "part"
    T_parent_marker: np.ndarray    # pose of the marker in its parent frame


def default_layout(shoulder_height: float = 0.17, plate_offset: float = 0.038, reach: float = 0.42, size: float = 0.06) -> dict[int, Marker]:
    """Marker placement assumed by the tracker (print tags at ``size``; measure real placements and edit this):
        id 0  base top face, flat, at (0, -0.14, 0.10) in the world frame
        id 1  Link-1 +y plate, outer face, mid-link        (tag z = link +y, tag x = link z, tag y = link x)
        id 3  Link-1 -y plate, outer face, mid-link        (tag z = link -y, tag x = link z, tag y = link -x)
        id 2  top of the part (placed at its centre when seen)
    """
    p_link = [0.0, plate_offset, reach * 0.5]
    R_plus = np.column_stack([[0, 0, 1.0], [1.0, 0, 0], [0, 1.0, 0]])
    R_minus = np.column_stack([[0, 0, 1.0], [-1.0, 0, 0], [0, -1.0, 0]])
    return {
        0: Marker(0, size, "world", T(np.eye(3), [0.0, -0.14, 0.10])),
        1: Marker(1, size, "link", T(R_plus, p_link)),
        3: Marker(3, size, "link", T(R_minus, [0.0, -plate_offset, reach * 0.5])),
        2: Marker(2, size, "part", T(np.eye(3), [0.0, 0.0, 0.0])),
    }


def marker_corners(size: float) -> np.ndarray:
    """Corner points in the marker frame, in OpenCV ArUco order (top-left, top-right, bottom-right, bottom-left)."""
    h = size / 2
    return np.array([[-h, h, 0], [h, h, 0], [h, -h, 0], [-h, -h, 0]], float)
