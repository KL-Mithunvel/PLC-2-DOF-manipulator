"""Synthetic camera images of the tagged arm (for tests, accuracy studies and demos without hardware).

Renders the printed tags (with their white quiet zone) at their true 3D poses for a given (yaw, pitch, camera).
Back-facing tags are not drawn (a tag cannot be seen from behind).  No occlusion by the arm body is modelled.
"""
from __future__ import annotations

import cv2
import numpy as np

from .geometry import T, default_layout, inv, link_rotation, marker_corners
from .tracker import Camera

QUIET = 0.5            # quiet zone as a fraction of the marker side (printed tags need a white border)


def tag_image(marker_id: int, px: int = 240, dictionary=cv2.aruco.DICT_4X4_50) -> np.ndarray:
    d = cv2.aruco.getPredefinedDictionary(dictionary)
    img = cv2.aruco.generateImageMarker(d, marker_id, px)
    pad = int(px * QUIET)
    return cv2.copyMakeBorder(img, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)


def _project(cam: Camera, T_wc: np.ndarray, pts_w: np.ndarray) -> np.ndarray:
    T_cw = inv(T_wc)
    rvec, _ = cv2.Rodrigues(T_cw[:3, :3])
    out, _ = cv2.projectPoints(pts_w.astype(np.float64), rvec, T_cw[:3, 3], cam.K, cam.dist)
    return out.reshape(-1, 2)


def render(cam: Camera, T_wc: np.ndarray, phi: float, theta: float, layout=None, part_pos=None,
           shoulder_height: float = 0.17, noise: float = 0.0, seed: int = 0, background: int = 110) -> np.ndarray:
    layout = layout or default_layout(shoulder_height)
    W, H = cam.size
    img = np.full((H, W), background, np.uint8)
    T_wl = T(link_rotation(phi, theta), [0, 0, shoulder_height])
    cam_pos = T_wc[:3, 3]
    for mid, m in layout.items():
        if m.parent == "world":
            T_wm = m.T_parent_marker
        elif m.parent == "link":
            T_wm = T_wl @ m.T_parent_marker
        else:
            if part_pos is None:
                continue
            T_wm = T(np.eye(3), np.array(part_pos) + [0, 0, 0.0])
        normal = T_wm[:3, 2]
        if np.dot(normal, cam_pos - T_wm[:3, 3]) <= 0:
            continue
        s = m.size * (1 + 2 * QUIET)
        quad_m = np.array([[-s / 2, s / 2, 0], [s / 2, s / 2, 0], [s / 2, -s / 2, 0], [-s / 2, -s / 2, 0]])
        pts_w = (T_wm[:3, :3] @ quad_m.T).T + T_wm[:3, 3]
        dst = _project(cam, T_wc, pts_w).astype(np.float32)
        if (dst[:, 0].min() < 0 or dst[:, 1].min() < 0 or dst[:, 0].max() >= W or dst[:, 1].max() >= H):
            continue
        tag = tag_image(mid)
        th, tw = tag.shape
        src = np.array([[0, 0], [tw - 1, 0], [tw - 1, th - 1], [0, th - 1]], np.float32)
        Hm = cv2.getPerspectiveTransform(src, dst)
        warped = cv2.warpPerspective(tag, Hm, (W, H), flags=cv2.INTER_AREA)
        mask = cv2.warpPerspective(np.full_like(tag, 255), Hm, (W, H), flags=cv2.INTER_NEAREST)
        img = np.where(mask > 0, warped, img)
    if noise > 0:
        rng = np.random.default_rng(seed)
        img = np.clip(img.astype(np.float32) + rng.normal(0, noise, img.shape), 0, 255).astype(np.uint8)
    return img


def render_chessboard(cam: Camera, T_wc: np.ndarray, T_wb: np.ndarray, pattern=(9, 6), square: float = 0.03) -> np.ndarray:
    """Image of a flat chessboard (inner corners ``pattern``) lying in the z=0 plane of frame b."""
    W, H = cam.size
    nx, ny = pattern[0] + 1, pattern[1] + 1
    px = 40
    board = np.zeros((ny * px, nx * px), np.uint8)
    for j in range(ny):
        for i in range(nx):
            if (i + j) % 2 == 0:
                board[j * px:(j + 1) * px, i * px:(i + 1) * px] = 255
    pad = px
    board = cv2.copyMakeBorder(board, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)
    bw, bh = nx * square, ny * square
    m = square * pad / px
    quad = np.array([[-m, -m, 0], [bw + m, -m, 0], [bw + m, bh + m, 0], [-m, bh + m, 0]], float)
    pts_w = (T_wb[:3, :3] @ quad.T).T + T_wb[:3, 3]
    dst = _project(cam, T_wc, pts_w).astype(np.float32)
    h, w = board.shape
    src = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], np.float32)
    Hm = cv2.getPerspectiveTransform(src, dst)
    img = np.full((H, W), 90, np.uint8)
    warped = cv2.warpPerspective(board, Hm, (W, H), flags=cv2.INTER_AREA)
    mask = cv2.warpPerspective(np.full_like(board, 255), Hm, (W, H), flags=cv2.INTER_NEAREST)
    return np.where(mask > 0, warped, img)
