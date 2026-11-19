"""Rigid-body model of the 2-DOF arm from per-body mass properties (CAD-ready).

Generalised coordinates q = (phi, theta): base yaw about z and shoulder pitch (theta = 0: link vertical up).
Each body is attached to one of three frames:
    "yaw"   rotates with phi only          (base motor housing, pedestal, shoulder motor/joint body)
    "link"  rotates with phi and theta     (Link-1: origin on the shoulder axis, +z along the link, y = pitch axis)
    "drop"  origin at point P (link end), rotates with phi only (Link-2 + magnet + payload hang vertical)
``com`` is in the body's own frame, ``inertia`` the 3x3 tensor about the COM in that frame (kg.m^2).

Provides the joint-space dynamics  M(q) qdd + C(q,qd) qd + G(q) = tau  and the structural reaction loads.
Everything is plain Python (no numpy) and uses analytic orientations with finite-difference Jacobians.

CAD file format (``cad_mass_properties.json``, optional, replaces the default bodies):
  {"bodies": [{"name": "link1", "frame": "link", "mass": 2.31, "com": [0, 0, 0.19],
               "inertia": [[Ixx, Ixy, Ixz], [Ixy, Iyy, Iyz], [Ixz, Iyz, Izz]]}, ...]}   (inertia may also be [Ixx, Iyy, Izz])
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field

G = 9.81
Vec = list
Mat = list


def mat_mul(a: Mat, b: Mat) -> Mat:
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def mat_vec(a: Mat, v: Vec) -> Vec:
    return [sum(a[i][k] * v[k] for k in range(3)) for i in range(3)]


def transpose(a: Mat) -> Mat:
    return [[a[j][i] for j in range(3)] for i in range(3)]


def cross(a: Vec, b: Vec) -> Vec:
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def dot(a: Vec, b: Vec) -> float:
    return sum(x * y for x, y in zip(a, b))


def rz(a: float) -> Mat:
    c, s = math.cos(a), math.sin(a)
    return [[c, -s, 0], [s, c, 0], [0, 0, 1]]


def ry(a: float) -> Mat:
    c, s = math.cos(a), math.sin(a)
    return [[c, 0, s], [0, 1, 0], [-s, 0, c]]


@dataclass
class Body:
    name: str
    frame: str                      # yaw | link | drop
    mass: float
    com: Vec = field(default_factory=lambda: [0.0, 0.0, 0.0])
    inertia: Mat = field(default_factory=lambda: [[0.0] * 3 for _ in range(3)])
    active: bool = True             # e.g. the payload only counts while carried


def diag_inertia(ixx: float, iyy: float, izz: float) -> Mat:
    return [[ixx, 0, 0], [0, iyy, 0], [0, 0, izz]]


def default_bodies(arm_cfg) -> list[Body]:
    """Bodies equivalent to the paper's simplified model (link-1 uniform rod, link-2 + payload as point masses at P)."""
    a = arm_cfg
    L = a.reach
    return [
        Body("base_struct", "yaw", 0.0, inertia=diag_inertia(0, 0, a.j_base_struct)),   # only the base-axis inertia is known
        Body("link1", "link", a.m_link1, [0, 0, L / 2], diag_inertia(a.m_link1 * L * L / 12, a.m_link1 * L * L / 12, 0.0)),
        Body("link2", "drop", a.m_link2, [0, 0, 0]),
        Body("payload", "drop", a.payload, [0, 0, 0], active=False),
    ]


def load_cad_bodies(path: str) -> list[Body]:
    with open(path) as fh:
        data = json.load(fh)
    out = []
    for b in data["bodies"]:
        i = b.get("inertia", [0, 0, 0])
        inertia = diag_inertia(*i) if len(i) == 3 and not isinstance(i[0], list) else [list(map(float, r)) for r in i]
        out.append(Body(b["name"], b["frame"], float(b["mass"]), list(map(float, b.get("com", [0, 0, 0]))), inertia,
                        active=b.get("active", True)))
    return out


class ArmModel:
    def __init__(self, bodies: list[Body], reach: float, shoulder_height: float) -> None:
        self.bodies = bodies
        self.L = reach
        self.h = shoulder_height

    def body(self, name: str) -> Body:
        return next(b for b in self.bodies if b.name == name)

    # ---- kinematics of one body ---------------------------------------------
    def _pose(self, b: Body, q: Vec) -> tuple[Vec, Mat]:
        phi, th = q
        Rz = rz(phi)
        if b.frame == "yaw":
            R = Rz
            origin = [0.0, 0.0, 0.0]
        elif b.frame == "link":
            R = mat_mul(Rz, ry(th))
            origin = mat_vec(Rz, [0.0, 0.0, self.h])
        elif b.frame == "drop":
            R = Rz
            origin = mat_vec(Rz, [self.L * math.sin(th), 0.0, self.h + self.L * math.cos(th)])
        else:
            raise ValueError(b.frame)
        c = mat_vec(R, b.com)
        return [origin[i] + c[i] for i in range(3)], R

    def _omega(self, b: Body, q: Vec, qd: Vec) -> Vec:
        phi, th = q
        w = [0.0, 0.0, qd[0]]
        if b.frame == "link":
            ay = mat_vec(rz(phi), [0.0, 1.0, 0.0])
            w = [w[i] + qd[1] * ay[i] for i in range(3)]
        return w

    def _jac(self, b: Body, q: Vec) -> tuple[list[Vec], list[Vec]]:
        """(Jv columns, Jw columns): 2 columns of 3-vectors."""
        eps = 1e-6
        jv = []
        for k in range(2):
            qp, qm = list(q), list(q)
            qp[k] += eps
            qm[k] -= eps
            pp, pm = self._pose(b, qp)[0], self._pose(b, qm)[0]
            jv.append([(pp[i] - pm[i]) / (2 * eps) for i in range(3)])
        jw = [self._omega(b, q, [1.0, 0.0]), self._omega(b, q, [0.0, 1.0])]
        return jv, jw

    def _world_inertia(self, b: Body, q: Vec) -> Mat:
        R = self._pose(b, q)[1]
        return mat_mul(mat_mul(R, b.inertia), transpose(R))

    # ---- dynamics ---------------------------------------------------------------
    def mass_matrix(self, q: Vec) -> Mat:
        M = [[0.0, 0.0], [0.0, 0.0]]
        for b in self.bodies:
            if not b.active:
                continue
            jv, jw = self._jac(b, q)
            Iw = self._world_inertia(b, q)
            for i in range(2):
                Iwj = [mat_vec(Iw, jw[j]) for j in range(2)]
                for j in range(2):
                    M[i][j] += b.mass * dot(jv[i], jv[j]) + dot(jw[i], Iwj[j])
        return M

    def gravity(self, q: Vec) -> Vec:
        """G(q) = dV/dq."""
        G_ = [0.0, 0.0]
        for b in self.bodies:
            if not b.active:
                continue
            jv, _ = self._jac(b, q)
            for i in range(2):
                G_[i] += b.mass * G * jv[i][2]
        return G_

    def coriolis(self, q: Vec, qd: Vec) -> Vec:
        """C(q,qd) qd via the Christoffel symbols (finite-difference dM/dq)."""
        eps = 1e-6
        dM = []
        for k in range(2):
            qp, qm = list(q), list(q)
            qp[k] += eps
            qm[k] -= eps
            Mp, Mm = self.mass_matrix(qp), self.mass_matrix(qm)
            dM.append([[(Mp[i][j] - Mm[i][j]) / (2 * eps) for j in range(2)] for i in range(2)])
        out = [0.0, 0.0]
        for i in range(2):
            for j in range(2):
                for k in range(2):
                    c = 0.5 * (dM[k][i][j] + dM[j][i][k] - dM[i][j][k])
                    out[i] += c * qd[j] * qd[k]
        return out

    def external_torques(self, q: Vec, qd: Vec, qdd: Vec) -> tuple[Vec, Vec]:
        """Returns (inertia diagonal [M11, M22], torque-on-joint-from-everything-else [t1, t2]) in the form the
        Axis expects: J_i * alpha_i = tau_i + t_ext_i, with t_ext_i = -G_i - (C qd)_i - sum_{j!=i} M_ij qdd_j."""
        M = self.mass_matrix(q)
        G_ = self.gravity(q)
        C = self.coriolis(q, qd)
        t = [-G_[0] - C[0] - M[0][1] * qdd[1], -G_[1] - C[1] - M[1][0] * qdd[0]]
        return [M[0][0], M[1][1]], t

    # ---- structural reaction loads --------------------------------------------------
    def _acc(self, b: Body, q: Vec, qd: Vec, qdd: Vec) -> tuple[Vec, Vec]:
        """COM linear acceleration and angular acceleration by second differences along the motion."""
        h = 1e-3

        def state(t):
            qt = [q[i] + qd[i] * t + 0.5 * qdd[i] * t * t for i in range(2)]
            qdt = [qd[i] + qdd[i] * t for i in range(2)]
            return qt, qdt

        p0 = self._pose(b, q)[0]
        pp, pm = self._pose(b, state(h)[0])[0], self._pose(b, state(-h)[0])[0]
        a = [(pp[i] - 2 * p0[i] + pm[i]) / (h * h) for i in range(3)]
        wp = self._omega(b, *state(h))
        wm = self._omega(b, *state(-h))
        alpha = [(wp[i] - wm[i]) / (2 * h) for i in range(3)]
        return a, alpha

    def reactions(self, q: Vec, qd: Vec, qdd: Vec, subtree: str = "flange") -> dict:
        """Force (N) and moment (N.m) that the support applies to the moving bodies, world frame, about the support point.
        subtree: "flange" = everything above the base housing (support point: base axis at z=0)
                 "shoulder" = link + drop bodies (support point: shoulder axis)."""
        origin = [0.0, 0.0, 0.0] if subtree == "flange" else mat_vec(rz(q[0]), [0.0, 0.0, self.h])
        F = [0.0, 0.0, 0.0]
        Mo = [0.0, 0.0, 0.0]
        for b in self.bodies:
            if not b.active or (subtree == "shoulder" and b.frame == "yaw"):
                continue
            p = self._pose(b, q)[0]
            a, alpha = self._acc(b, q, qd, qdd)
            w = self._omega(b, q, qd)
            f = [b.mass * (a[i] + (G if i == 2 else 0.0)) for i in range(3)]      # support force on body = m(a - g), g = -G z
            r = [p[i] - origin[i] for i in range(3)]
            Iw = self._world_inertia(b, q)
            iw = mat_vec(Iw, w)
            m_i = [x + y for x, y in zip(mat_vec(Iw, alpha), cross(w, iw))]
            mom = [x + y for x, y in zip(cross(r, f), m_i)]
            F = [F[i] + f[i] for i in range(3)]
            Mo = [Mo[i] + mom[i] for i in range(3)]
        return {"force": F, "moment": Mo,
                "bending": math.hypot(Mo[0], Mo[1]), "axial": F[2], "torsion": Mo[2]}
