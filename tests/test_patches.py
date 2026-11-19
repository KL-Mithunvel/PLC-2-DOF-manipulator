import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from twin.config import TwinCfg
from twin.sim import Twin


def run_until_magnet(cfg):
    t = Twin(cfg)
    for _ in range(800):
        t.tick()
    t.command({"type": "button", "tag": "START", "down": True})
    for _ in range(3000):
        t.tick()
        if t.plc.mem.read("Q0.7"):
            break
    t.command({"type": "button", "tag": "START", "down": False})
    return t


class EstopMagnet(unittest.TestCase):
    def estop_cycle(self, fix):
        cfg = TwinCfg()
        cfg.fix_estop_magnet_latch = fix
        t = run_until_magnet(cfg)
        self.assertTrue(t.plc.mem.read("Q0.7"))
        t.command({"type": "estop", "pressed": True})
        for _ in range(100):
            t.tick()
        t.command({"type": "estop", "pressed": False})
        for _ in range(100):
            t.tick()
        return t.plc.mem.read("Q0.7")

    def test_original_program_re_energises_magnet(self):
        self.assertEqual(self.estop_cycle(False), 1)       # documented bug of the real program

    def test_patch_keeps_magnet_off(self):
        self.assertEqual(self.estop_cycle(True), 0)


class VW2400Overlap(unittest.TestCase):
    def test_original_corrupts_taught_init_and_fix_does_not(self):
        for fix, expect_equal in ((False, False), (True, True)):
            cfg = TwinCfg()
            cfg.fix_vw2400_overlap = fix
            t = Twin(cfg)
            taught = t.plc.mem.read("VD2400")
            for _ in range(800):
                t.tick()
            self.assertEqual(t.plc.mem.read("VD2400") == taught, expect_equal, f"fix={fix}")


class StartTap(unittest.TestCase):
    def test_short_start_tap_does_not_enable_drives_at_slow_timer_base(self):
        cfg = TwinCfg()
        cfg.timer_base_ms = 100                 # T2 = 10 units = 1 s enable delay
        t = Twin(cfg)
        for _ in range(800):
            t.tick()
        t.command({"type": "button", "tag": "START", "down": True})
        for _ in range(60):                     # 0.3 s tap
            t.tick()
        t.command({"type": "button", "tag": "START", "down": False})
        for _ in range(600):
            t.tick()
        self.assertFalse(t.arm.base.enabled)    # the ladder only enables while M30.0 is held for the delay


if __name__ == "__main__":
    unittest.main()
