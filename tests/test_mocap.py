import math
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mocap import placement
from mocap.calibrate import calibrate
from mocap.geometry import T, angles_from_link_rotation, link_rotation, look_at
from mocap.synth import render, render_chessboard
from mocap.tracker import Camera, Tracker

K = np.array([[1650.0, 0, 960], [0, 1650.0, 540], [0, 0, 1]])        # 1080p camera, ~63 deg horizontal field of view
CAM = Camera(K, np.zeros(5), (1920, 1080))
T_WC = look_at((-0.5, 0.7, 0.6), (0.1, 0.05, 0.25))


class Geometry(unittest.TestCase):
    def test_angle_roundtrip(self):
        for phi in (-1.0, 0.0, 0.7, 1.57, 3.0):
            for th in (-0.3, 0.0, 0.5, 1.5, 2.5):
                p, t = angles_from_link_rotation(link_rotation(phi, th))
                self.assertAlmostEqual(math.atan2(math.sin(p - phi), math.cos(p - phi)), 0.0, places=9)
                self.assertAlmostEqual(t, th, places=9)


class TrackerAccuracy(unittest.TestCase):
    def test_angles_recovered(self):
        trk = Tracker(CAM)
        worst = 0.0
        for phi in (0, 30, 60, 90):
            for th in (10, 55, 86):
                img = render(CAM, T_WC, math.radians(phi), math.radians(th), noise=2.0, seed=phi + th)
                est = trk.estimate(img)
                self.assertIsNotNone(est, f"no estimate at yaw {phi} pitch {th}")
                worst = max(worst, abs(est.base_deg - phi), abs(est.shoulder_deg - th))
        print(f"\n  tracker worst angle error over the grid: {worst:.2f} deg")
        self.assertLess(worst, 1.0)

    def test_camera_pose_recovered(self):
        est = Tracker(CAM).estimate(render(CAM, T_WC, 0.3, 0.9))
        self.assertLess(np.linalg.norm(est.cam_pose[:3, 3] - T_WC[:3, 3]), 0.02)       # within 2 cm

    def test_no_base_tag_gives_none(self):
        self.assertIsNone(Tracker(CAM).estimate(np.full((1080, 1920), 110, np.uint8)))

    def test_part_tag_position(self):
        img = render(CAM, T_WC, 0.0, 1.0, part_pos=[0.30, 0.05, 0.05])
        est = Tracker(CAM).estimate(img)
        self.assertIsNotNone(est.part_world)
        self.assertLess(np.linalg.norm(np.array(est.part_world) - [0.30, 0.05, 0.05]), 0.02)


class Calibration(unittest.TestCase):
    def test_recovers_focal_length(self):
        truth = Camera(np.array([[900.0, 0, 650], [0, 900.0, 350], [0, 0, 1]]), np.zeros(5), (1280, 720))
        imgs = []
        rng = np.random.default_rng(3)
        T_wb = T(np.eye(3), [-0.15, -0.1, 0])
        for k in range(16):
            az = rng.uniform(-60, 60)
            pos = (0.0 + 0.7 * math.sin(math.radians(az)), -0.7 * math.cos(math.radians(az)), rng.uniform(0.35, 0.8))
            imgs.append(render_chessboard(truth, look_at(pos, (0.0 + rng.uniform(-0.05, 0.05), 0.0, 0.0)), T_wb))
        cam, rms, n = calibrate(imgs)
        self.assertGreaterEqual(n, 10)
        self.assertAlmostEqual(cam.K[0, 0], 900.0, delta=900 * 0.03)
        self.assertLess(rms, 1.0)

    def test_too_few_images_rejected(self):
        with self.assertRaises(ValueError):
            calibrate([np.full((720, 1280), 100, np.uint8)] * 3)


class Placement(unittest.TestCase):
    def test_only_the_anti_diagonal_sees_a_plate_tag_over_the_whole_yaw_sweep(self):
        # tags on both plates (+y and -y): over yaw 0..90 the plate normals sweep through the 135/315 deg azimuth directions
        for good in ((-0.5, 0.5, 0.6), (0.6, -0.6, 0.6)):
            self.assertLess(placement.worst_case(good), 65, good)
        for bad in ((0.6, 0.6, 0.6), (0.0, 0.8, 0.6), (0.8, 0.0, 0.6)):
            self.assertGreater(placement.worst_case(bad), 85, bad)
        best = placement.search()[0]
        self.assertIn(best[1], (135, 315))
        self.assertLess(best[0], 65)

if __name__ == "__main__":
    unittest.main()
