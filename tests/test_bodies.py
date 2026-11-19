import json
import math
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from twin.bodies import ArmModel, Body, default_bodies, diag_inertia, load_cad_bodies
from twin.config import G, TwinCfg
from twin.plant import Arm


def model(payload_on=True):
    cfg = TwinCfg()
    bodies = default_bodies(cfg.arm)
    next(b for b in bodies if b.name == "payload").active = payload_on
    return cfg, ArmModel(bodies, cfg.arm.reach, cfg.arm.shoulder_height)


class Regression(unittest.TestCase):
    """The rigid-body model must reproduce the paper's point-mass formulas when fed the same masses."""

    def test_matches_simple_model(self):
        for payload in (True, False):
            cfg, m = model(payload)
            arm = Arm(cfg)
            arm.part = None
            if payload:
                from twin.plant import Part
                arm.part = Part([0, 0, 0], "carried", cfg.arm.payload)
            for th_deg in (0, 20, 55, 86, 90, 120):
                th = math.radians(th_deg)
                arm.shoulder.theta = th
                j_b, j_s, t_g, _ = arm.loads()
                M = m.mass_matrix([0.3, th])
                Gv = m.gravity([0.3, th])
                self.assertAlmostEqual(M[1][1], j_s, places=5, msg=f"J_sh at {th_deg}")
                self.assertAlmostEqual(M[0][0], j_b, places=5, msg=f"J_base at {th_deg}")
                self.assertAlmostEqual(-Gv[1], t_g, places=5, msg=f"gravity at {th_deg}")
                self.assertAlmostEqual(Gv[0], 0.0, places=6)
                self.assertAlmostEqual(M[0][1], 0.0, places=6)

    def test_paper_holding_torque(self):
        cfg, m = model(True)
        self.assertAlmostEqual(-m.gravity([0, math.pi / 2])[1], 30.9, delta=0.2)     # paper table 5.1


class Dynamics(unittest.TestCase):
    def test_static_reaction_equals_weight_and_overturning_moment(self):
        cfg, m = model(True)
        r = m.reactions([0.4, math.radians(90)], [0, 0], [0, 0])
        total = (cfg.arm.m_link1 + cfg.arm.m_link2 + cfg.arm.payload)
        self.assertAlmostEqual(r["axial"], total * G, places=3)
        self.assertAlmostEqual(r["bending"], 30.9, delta=0.2)            # overturning moment ~ shoulder torque (paper 5.2)
        self.assertAlmostEqual(r["torsion"], 0.0, places=3)

    def test_vertical_arm_has_no_overturning_moment(self):
        _, m = model(True)
        self.assertAlmostEqual(m.reactions([0, 0], [0, 0], [0, 0])["bending"], 0.0, places=4)

    def test_energy_consistency_of_coriolis(self):
        """d/dt (1/2 qd'M qd) = qd'(tau - G) for tau = 0 requires qd'(dM/dt/2 - C) qd = 0."""
        _, m = model(True)
        q, qd = [0.2, 0.9], [0.7, -0.4]
        C = m.coriolis(q, qd)
        eps = 1e-6
        dMdt = [[0, 0], [0, 0]]
        Mp = m.mass_matrix([q[0] + qd[0] * eps, q[1] + qd[1] * eps])
        Mm = m.mass_matrix([q[0] - qd[0] * eps, q[1] - qd[1] * eps])
        for i in range(2):
            for j in range(2):
                dMdt[i][j] = (Mp[i][j] - Mm[i][j]) / (2 * eps)
        lhs = sum(qd[i] * dMdt[i][j] * qd[j] for i in range(2) for j in range(2)) / 2
        rhs = sum(qd[i] * C[i] for i in range(2))
        self.assertAlmostEqual(lhs, rhs, delta=1e-3)

    def test_coupling_from_offset_inertia(self):
        """A body whose COM is off the link plane (along the pitch axis) gives base/shoulder coupling (M12 != 0); the simple model cannot."""
        cfg = TwinCfg()
        bodies = default_bodies(cfg.arm) + [Body("bracket", "link", 0.5, [0.0, 0.03, 0.2], diag_inertia(1e-3, 1e-3, 1e-3))]
        m = ArmModel(bodies, cfg.arm.reach, cfg.arm.shoulder_height)
        self.assertGreater(abs(m.mass_matrix([0.0, 0.8])[0][1]), 1e-5)


class CadFile(unittest.TestCase):
    def test_load_cad_json(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "cad.json")
            json.dump({"bodies": [{"name": "link1", "frame": "link", "mass": 2.5, "com": [0, 0, 0.2], "inertia": [0.02, 0.02, 0.001]},
                                  {"name": "x", "frame": "drop", "mass": 1, "inertia": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}]}, open(p, "w"))
            bodies = load_cad_bodies(p)
        self.assertEqual([b.name for b in bodies], ["link1", "x"])
        self.assertEqual(bodies[0].inertia[1][1], 0.02)


if __name__ == "__main__":
    unittest.main()
