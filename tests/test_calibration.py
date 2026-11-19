import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.calibrate_cycle import fit, simulate_run
from twin.config import TwinCfg, apply_overrides, load_config


class Overrides(unittest.TestCase):
    def test_dotted_overrides_and_file(self):
        cfg = apply_overrides(TwinCfg(), {"timer_base_ms": 100, "base.profile_rpm": 321, "arm.shoulder_height": 0.2})
        self.assertEqual((cfg.timer_base_ms, cfg.base.profile_rpm, cfg.arm.shoulder_height), (100, 321, 0.2))
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "c.json")
            json.dump({"shoulder.profile_rpm": 250}, open(p, "w"))
            self.assertEqual(load_config(p).shoulder.profile_rpm, 250)

    def test_unknown_key_rejected(self):
        with self.assertRaises(KeyError):
            apply_overrides(TwinCfg(), {"base.nonsense": 1})


class Calibration(unittest.TestCase):
    def test_fit_recovers_known_speed(self):
        truth = simulate_run({"base.profile_rpm": 300, "shoulder.profile_rpm": 300}, cycles=1)
        res = fit(truth, cycles=1, param="profile_rpm", tol=0.01)
        self.assertAlmostEqual(res["simulated_s"], truth, delta=truth * 0.02)

    def test_fit_timer_base(self):
        truth = simulate_run({"timer_base_ms": 40}, cycles=1)
        res = fit(truth, cycles=1, param="timer_base_ms", tol=0.01)
        self.assertAlmostEqual(res["value"], 40, delta=6)


if __name__ == "__main__":
    unittest.main()
