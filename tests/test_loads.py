import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from twin.config import TwinCfg
from twin.plant import Arm, Part
from twin.sim import Twin


def pose_arm(theta_deg, payload=True):
    cfg = TwinCfg()
    arm = Arm(cfg)
    arm.shoulder.theta = math.radians(theta_deg)
    arm.part = Part([0, 0, 0], "carried", 5.0) if payload else None
    return arm


class Structural(unittest.TestCase):
    def test_pose_a_reproduces_ansys_stresses(self):
        st = pose_arm(90).structural_state()
        b = st["bodies"]
        self.assertAlmostEqual(b["joint"]["stress_mpa"], 8.81, places=2)
        self.assertAlmostEqual(b["link1"]["stress_mpa"], 4.44, places=2)
        self.assertAlmostEqual(b["link2"]["defl_um"], 85.2, delta=0.5)
        self.assertAlmostEqual(st["moment_flange"], 30.9, delta=0.2)
        self.assertEqual(st["min_fos"], 15.0)

    def test_load_scales_with_payload_and_pose(self):
        full = pose_arm(90)
        light = pose_arm(90, payload=False)
        raised = pose_arm(45)
        s_full = full.structural_state()["bodies"]["joint"]["stress_mpa"]
        self.assertLess(light.structural_state()["bodies"]["joint"]["stress_mpa"], s_full * 0.4)   # unloaded: ~8.4 of 30.9 N.m
        self.assertAlmostEqual(raised.structural_state()["bodies"]["joint"]["stress_mpa"], s_full * math.sin(math.radians(45)), delta=0.05)
        vertical = pose_arm(0).structural_state()
        self.assertAlmostEqual(vertical["moment_flange"], 0.0, places=3)

    def test_dynamic_term_adds_to_static(self):
        arm = pose_arm(60)
        static = arm.structural_state()["moment_shoulder"]
        arm.shoulder.omega, arm.base.omega = 0.5, 0.8
        arm._alpha_f = [3.0, 4.0]
        self.assertNotAlmostEqual(arm.structural_state()["moment_shoulder"], static, places=2)


class RigidBodyMode(unittest.TestCase):
    def cycle(self, rigid):
        cfg = TwinCfg()
        cfg.arm.use_rigid_body = rigid
        t = Twin(cfg)
        for _ in range(800):
            t.tick()
        t.command({"type": "button", "tag": "START", "down": True})
        peak, fos, n = 0.0, 15.0, 0
        for i in range(int(40 / 0.005)):
            t.tick()
            if i == 60:
                t.command({"type": "button", "tag": "START", "down": False})
            peak = max(peak, abs(t.arm.shoulder.tau))
            n += 1
            if t.plc.mem.read("M30.2"):
                break
        return t, peak

    def test_full_cycle_matches_simple_model(self):
        t_simple, p_simple = self.cycle(False)
        t_rigid, p_rigid = self.cycle(True)
        self.assertEqual((t_rigid.arm.picks, t_rigid.arm.drops), (3, 3))
        self.assertAlmostEqual(p_rigid, p_simple, delta=p_simple * 0.1)
        self.assertAlmostEqual(t_rigid.t, t_simple.t, delta=0.5)


class SnapshotFields(unittest.TestCase):
    def test_structural_in_snapshot_and_scope(self):
        t = Twin()
        for _ in range(100):
            t.tick()
        s = t.snapshot()
        self.assertIn("min_fos", s["structural"])
        self.assertIn("fos_min", t.scope[-1])


if __name__ == "__main__":
    unittest.main()
