import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from twin.sim import Twin


class LiveConfig(unittest.TestCase):
    def test_reconfigure_keeps_state_and_applies(self):
        t = Twin()
        t.plc.mem.write("VW2036", 7)
        for _ in range(800):
            t.tick()
        theta = t.arm.shoulder.theta
        cfg = t.reconfigure({"timer_base_ms": 40, "base.profile_rpm": 222, "fix_estop_magnet_latch": True})
        self.assertEqual(cfg["timer_base_ms"], 40)
        self.assertEqual(t.plc.mem.read("VW2036"), 7)                 # retentive data kept
        self.assertEqual(t.arm.shoulder.theta, theta)                 # pose kept
        self.assertTrue(t.plc.can_online)
        self.assertEqual(t.plc.vm.timer_base_ms, 40)
        self.assertEqual(t.arm.base.cfg.profile_rpm, 222)
        self.assertTrue(any(i.text.startswith("R") and "M30.6" in i.text and i.net == 39 for i in t.plc.program.instrs))
        for _ in range(100):
            t.tick()                                                   # still runs

    def test_whitelist(self):
        with self.assertRaises(KeyError):
            Twin().reconfigure({"scan_ms": 1})
        r = Twin().command({"type": "config_get"})
        self.assertIn("timer_base_ms", r["keys"])

    def test_save_writes_override_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "twin_config.json")
            with mock.patch("twin.sim.OVERRIDE_FILE", path):
                Twin().reconfigure({"shoulder.profile_rpm": 321}, save=True)
            self.assertEqual(json.load(open(path))["shoulder.profile_rpm"], 321)


if __name__ == "__main__":
    unittest.main()
