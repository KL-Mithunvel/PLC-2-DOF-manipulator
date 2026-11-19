"""Structural load estimate (stress, deformation, factor of safety) from the live reaction loads.

NOT a live FEA solve.  The structure is linear and lightly loaded (peak 8.81 MPa against 250 MPa yield in the
Ansys study), so every body's stress and deformation are scaled linearly with the bending moment it carries:

    value_i(t) = value_i(Pose A) * M_i(t) / M_i(Pose A)

where Pose A is the Ansys pick-up pose (arm extended horizontally over the origin, 5 kg held) and M_i is the
bending moment from the rigid-body model (twin/bodies.py), including dynamic terms:
    base + joint bodies -> overturning moment at the base flange
    link-1 + link-2     -> bending moment at the shoulder axis
When real FEA results for more poses are available, replace the reference table by a lookup.

Reference values: docs/paper (Ansys 2023 R1 study, tables in section 4).  Known inconsistency in the paper itself
(its section 7): the joint's reported FOS (9.79 at Pose A, 4.63 at Pose B) does not follow from its stress plot
(8.81 MPa -> FOS 28, capped at 15).  The scaled-stress FOS below is self-consistent; the Ansys-reported values are
returned separately as ``ansys_ref`` so graphs can show both.
"""
from __future__ import annotations

import math

FOS_CAP = 15.0

# body -> (yield MPa, stress at Pose A MPa, max deformation at Pose A um, at Pose B um, which moment)
REF = {
    "base":  {"yield": 250.0, "stress_a": 5.15, "defl_a": 1.6,  "defl_b": 0.5,  "moment": "flange"},
    "joint": {"yield": 250.0, "stress_a": 8.81, "defl_a": 7.1,  "defl_b": 3.7,  "moment": "flange"},
    "link1": {"yield": 259.2, "stress_a": 4.44, "defl_a": 83.4, "defl_b": 65.2, "moment": "shoulder"},
    "link2": {"yield": 259.2, "stress_a": 1.13, "defl_a": 85.2, "defl_b": 68.6, "moment": "shoulder"},
}
ANSYS_FOS = {"joint": {"pose_a": 9.79, "pose_b": 4.63}, "link1": {"pose_a": FOS_CAP, "pose_b": 9.02},
             "base": {"pose_a": FOS_CAP, "pose_b": FOS_CAP}, "link2": {"pose_a": FOS_CAP, "pose_b": FOS_CAP}}
POSE_A = (0.0, math.pi / 2)          # (base yaw, shoulder pitch): arm horizontal


class StructuralModel:
    def __init__(self, arm_model, payload_kg: float = 5.0) -> None:
        self.m = arm_model
        # reference moments from the model itself at Pose A with the 5 kg payload on
        pl = self._payload()
        saved = (pl.active, pl.mass) if pl else None
        if pl:
            pl.active, pl.mass = True, payload_kg
        self.ref_moment = {
            "flange": arm_model.reactions(list(POSE_A), [0, 0], [0, 0], "flange")["bending"],
            "shoulder": arm_model.reactions(list(POSE_A), [0, 0], [0, 0], "shoulder")["bending"],
        }
        if pl:
            pl.active, pl.mass = saved
        # Ansys Pose B (holding at 90 deg base, link raised): used only for the reference deformation ratio
        self.stress_scale = {k: 1.0 for k in REF}      # calibration knob per body (e.g. stress concentration)

    def _payload(self):
        return next((b for b in self.m.bodies if b.name == "payload"), None)

    def evaluate(self, q, qd, qdd) -> dict:
        r_f = self.m.reactions(q, qd, qdd, "flange")
        r_s = self.m.reactions(q, qd, qdd, "shoulder")
        moments = {"flange": r_f["bending"], "shoulder": r_s["bending"]}
        bodies, min_fos, min_body = {}, FOS_CAP, ""
        for name, ref in REF.items():
            ratio = moments[ref["moment"]] / self.ref_moment[ref["moment"]] if self.ref_moment[ref["moment"]] else 0.0
            stress = ref["stress_a"] * ratio * self.stress_scale[name]
            fos = FOS_CAP if stress < 1e-9 else min(FOS_CAP, ref["yield"] / stress)
            bodies[name] = {"stress_mpa": stress, "defl_um": ref["defl_a"] * ratio, "fos": fos, "yield_mpa": ref["yield"]}
            if fos < min_fos:
                min_fos, min_body = fos, name
        return {
            "moment_flange": moments["flange"], "moment_shoulder": moments["shoulder"],
            "axial_n": r_f["axial"], "torsion_nm": r_f["torsion"],
            "bodies": bodies, "min_fos": min_fos, "min_fos_body": min_body,
            "tip_defl_um": bodies["link2"]["defl_um"],
            "ref_moment": self.ref_moment,
            "ansys_ref": {"min_fos": 4.63, "min_fos_body": "joint (pose B)", "max_defl_um": 85.2, "max_stress_mpa": 8.81,
                          "fos": ANSYS_FOS},
        }
