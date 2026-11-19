import json
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools import import_cad
from tools.meshio import box_mesh, mass_properties, read_mesh, write_glb, write_stl
from twin.bodies import ArmModel, load_cad_bodies
from twin.config import ArmCfg, TwinCfg


class MassProps(unittest.TestCase):
    def test_box_analytic(self):
        a, b, c, rho = 0.1, 0.2, 0.3, 2713.0
        mp = mass_properties(box_mesh(a, b, c, center=(1.0, 2.0, 3.0)), rho)
        m = rho * a * b * c
        self.assertAlmostEqual(mp["mass"], m, places=6)
        for got, want in zip(mp["com"], (1.0, 2.0, 3.0)):
            self.assertAlmostEqual(got, want, places=9)
        self.assertAlmostEqual(mp["inertia"][0][0], m * (b * b + c * c) / 12, places=6)
        self.assertAlmostEqual(mp["inertia"][1][1], m * (a * a + c * c) / 12, places=6)
        self.assertAlmostEqual(mp["inertia"][2][2], m * (a * a + b * b) / 12, places=6)
        self.assertAlmostEqual(mp["inertia"][0][1], 0.0, places=8)

    def test_inverted_winding_tolerated(self):
        flipped = [(t[0], t[2], t[1]) for t in box_mesh(0.1, 0.1, 0.1)]
        self.assertAlmostEqual(mass_properties(flipped, 1000.0)["mass"], 1.0, places=6)

    def test_open_mesh_rejected(self):
        with self.assertRaises(ValueError):
            mass_properties([], 1000.0)


class Files(unittest.TestCase):
    def test_stl_roundtrip_and_scale(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "b.stl")
            write_stl(p, box_mesh(100, 200, 300))             # "millimetres"
            mp = mass_properties(read_mesh(p, 0.001), 1000.0)
            self.assertAlmostEqual(mp["mass"], 0.1 * 0.2 * 0.3 * 1000, places=5)

    def test_glb_is_valid(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "b.glb")
            write_glb(p, box_mesh(0.1, 0.1, 0.1))
            data = open(p, "rb").read()
        magic, ver, total = struct.unpack_from("<III", data, 0)
        self.assertEqual((magic, ver, total), (0x46546C67, 2, len(data)))
        jlen, jtype = struct.unpack_from("<II", data, 12)
        gltf = json.loads(data[20:20 + jlen])
        self.assertEqual(jtype, 0x4E4F534A)
        self.assertEqual(gltf["accessors"][0]["count"], 36)
        self.assertEqual(len(data) % 4, 0)


class Pipeline(unittest.TestCase):
    def test_import_to_physics(self):
        """Build the default arm out of boxes with the same masses as the paper; physics must agree with the simple model."""
        arm = ArmCfg()
        L, h = arm.reach, arm.shoulder_height
        with tempfile.TemporaryDirectory() as d:
            link1 = os.path.join(d, "link1.stl")
            link2 = os.path.join(d, "link2.stl")
            base = os.path.join(d, "base.stl")
            write_stl(link1, box_mesh(0.04, 0.08, L, center=(0, 0, h + L / 2)))
            write_stl(link2, box_mesh(0.03, 0.03, 0.12, center=(0, 0, h + L)))
            write_stl(base, box_mesh(0.2, 0.2, 0.1, center=(0, 0, 0.05)))
            out = os.path.join(d, "cad.json")
            import_cad.main(["--body", f"base:yaw:{base}:7872", "--body", f"link1:link:{link1}:2713",
                             "--body", f"link2:drop:{link2}:2713", "--mass", "link1=2.0", "--mass", "link2=1.5",
                             "--payload-kg", "5", "--out-mass", out, "--models-dir", os.path.join(d, "models")])
            self.assertTrue(os.path.exists(os.path.join(d, "models", "link1.glb")))
            manifest = json.load(open(os.path.join(d, "models", "manifest.json")))
            self.assertEqual(manifest["bodies"]["link1"]["frame"], "link")
            bodies = load_cad_bodies(out)
        l1 = next(b for b in bodies if b.name == "link1")
        self.assertAlmostEqual(l1.com[2], L / 2, places=6)                 # COM relative to the shoulder axis
        self.assertAlmostEqual(next(b for b in bodies if b.name == "link2").com[2], 0.0, places=6)
        m = ArmModel(bodies, L, h)
        pl = next(b for b in bodies if b.name == "payload")
        pl.active = True
        import math
        # shoulder gravity torque at horizontal with 5 kg: close to the paper's 30.9 N.m (box COMs are exact, so within the box inertia effect)
        self.assertAlmostEqual(-m.gravity([0, math.pi / 2])[1], 30.9, delta=0.2)


if __name__ == "__main__":
    unittest.main()
