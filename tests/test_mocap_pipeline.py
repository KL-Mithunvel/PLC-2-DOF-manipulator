import os
import sys
import tempfile
import unittest

import cv2

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.compare_runs import compare
from tools.make_tags import main as make_tags_main
from tools.mocap_demo import run_demo


class Compare(unittest.TestCase):
    def synthetic(self, lag=0.0, bias=0.0):
        import math
        a, b = [], []
        for i in range(600):
            t = i * 0.04
            sh = 40 + 30 * math.sin(t * 0.6)
            bs = 45 + 45 * math.sin(t * 0.35 + 1)
            tip = [0.4 * math.sin(math.radians(sh)), 0.0, 0.2]
            a.append({"t": t, "base": {"deg": bs}, "shoulder": {"deg": sh}, "geom": {"tip": tip}})
            t2 = t + lag
            sh2 = sh + bias
            b.append({"t": t2, "base": {"deg": bs}, "shoulder": {"deg": sh2}, "geom": {"tip": [0.4 * math.sin(math.radians(sh2)), 0.0, 0.2]}})
        return a, b

    def test_lag_and_bias_recovered(self):
        a, b = self.synthetic(lag=1.3, bias=0.5)
        r = compare(a, b)
        self.assertAlmostEqual(r["lag_s"], -1.3, delta=0.03)
        self.assertAlmostEqual(r["shoulder_deg"]["bias"], -0.5, delta=0.05)
        self.assertAlmostEqual(r["base_deg"]["rms"], 0.0, delta=0.1)

    def test_identical_runs(self):
        a, _ = self.synthetic()
        r = compare(a, a)
        self.assertLess(r["tip_mm"]["max"], 1e-6)


class Demo(unittest.TestCase):
    def test_end_to_end_tracking_error(self):
        with tempfile.TemporaryDirectory() as d:
            res = run_demo(seconds=14, out_dir=d, lag_s=0.7)
            self.assertTrue(os.path.exists(os.path.join(d, "demo_mocap.jsonl")))
        print(f"\n  end-to-end: tracked {res['tracked']}/{res['frames']} frames, lag {res['lag_s']:.2f} s, "
              f"base rms {res['base_deg']['rms']:.2f} deg, shoulder rms {res['shoulder_deg']['rms']:.2f} deg, tip rms {res['tip_mm']['rms']:.1f} mm")
        self.assertGreater(res["tracked"] / res["frames"], 0.9)
        self.assertAlmostEqual(res["lag_s"], -0.7, delta=0.08)
        self.assertLess(res["shoulder_deg"]["rms"], 1.5)
        self.assertLess(res["tip_mm"]["rms"], 15)


class VideoFile(unittest.TestCase):
    def test_mocap_source_from_video_file(self):
        import time
        import numpy as np
        from mocap.source import MocapSource
        from mocap.tracker import Camera
        with tempfile.TemporaryDirectory() as d:
            video = os.path.join(d, "v.mp4")
            run_demo(seconds=7, out_dir=d, video=video, resolution=(1280, 720))
            f = 1650.0 * 1280 / 1920
            cam = Camera(np.array([[f, 0, 640], [0, f, 360], [0, 0, 1]]), np.zeros(5), (1280, 720))
            src = MocapSource.from_spec(video, cam).start()
            deadline = time.time() + 15
            while time.time() < deadline and src.seen < 20:
                time.sleep(0.1)
            snap = src.snapshot()
            src.stop()
        self.assertGreaterEqual(src.seen, 20)
        self.assertEqual(snap["source"], "mocap")
        self.assertIn("tags", snap["mocap"])
        self.assertTrue(src.status()["connected"] or src.seen > 0)


class Tags(unittest.TestCase):
    def test_make_tags_writes_detectable_png(self):
        with tempfile.TemporaryDirectory() as d:
            sys.argv = ["make_tags", "--out", d, "--ids", "1"]
            make_tags_main()
            img = cv2.imread(os.path.join(d, "tag_1.png"), cv2.IMREAD_GRAYSCALE)
            det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50))
            _, ids, _ = det.detectMarkers(img)
        self.assertEqual(ids.ravel().tolist(), [1])


if __name__ == "__main__":
    unittest.main()
