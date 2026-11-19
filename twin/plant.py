"""The mechanical plant: 2-DOF arm (base yaw + shoulder pitch), electromagnet and the 5 kg part."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import os

from .bodies import ArmModel, Body, default_bodies, load_cad_bodies
from .config import ArmCfg, G, TwinCfg
from .drive import Axis
from .loads import StructuralModel

CAD_MASS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cad_mass_properties.json")


@dataclass
class Part:
    pos: list[float]
    state: str = "free"      # free | carried | placed
    mass: float = 5.0


class Arm:
    def __init__(self, cfg: TwinCfg) -> None:
        self.cfg = cfg
        self.a: ArmCfg = cfg.arm
        self.base = Axis(cfg.base, 0.0)
        self.shoulder = Axis(cfg.shoulder, 0.0)
        self.part: Part | None = None
        self.placed: Part | None = None
        self.pick_site: list[float] | None = None
        self.events: list[str] = []
        self.drops = 0
        self.picks = 0
        # rigid-body model (always built: it also gives the structural reaction loads)
        cad = self.a.cad_mass_file or CAD_MASS_FILE
        if os.path.exists(cad):
            bodies = load_cad_bodies(cad)
            self.a.use_rigid_body = True
        else:
            bodies = default_bodies(self.a)
        if not any(b.name == "payload" for b in bodies):
            bodies.append(Body("payload", "drop", self.a.payload, [0, 0, 0], active=False))
        self.model = ArmModel(bodies, self.a.reach, self.a.shoulder_height)
        self.structural = StructuralModel(self.model, self.a.payload)
        self._cache_t = -1.0
        self._cache = None
        self._alpha_f = [0.0, 0.0]
        self.sim_t = 0.0

    # --- kinematics ------------------------------------------------------
    def fk(self, phi: float, theta: float) -> tuple[list[float], list[float], list[float]]:
        """Return (shoulder, P, tip) in metres. phi = base yaw, theta = shoulder pitch from vertical-up."""
        a = self.a
        sh = [0.0, 0.0, a.shoulder_height]
        r = a.reach * math.sin(theta)
        p = [r * math.cos(phi), r * math.sin(phi), a.shoulder_height + a.reach * math.cos(theta)]
        tip = [p[0], p[1], p[2] - a.drop_link]
        return sh, p, tip

    def tip(self) -> list[float]:
        return self.fk(self.base.theta, self.shoulder.theta)[2]

    def tip_from_counts(self, base_count: int, sh_count: int) -> list[float]:
        return self.fk(self.cfg.base.count_to_angle(base_count), self.cfg.shoulder.count_to_angle(sh_count))[2]

    # --- dynamics --------------------------------------------------------
    @property
    def carried_mass(self) -> float:
        return self.part.mass if self.part and self.part.state == "carried" else 0.0

    def _sync_payload(self) -> None:
        b = next(b for b in self.model.bodies if b.name == "payload")
        b.mass, b.active = self.carried_mass, self.carried_mass > 0

    def _q(self):
        return [self.base.theta, self.shoulder.theta], [self.base.omega, self.shoulder.omega], list(self._alpha_f)

    def loads(self) -> tuple[float, float, float, float]:
        """(J_base, J_shoulder, T_gravity_shoulder, payload_kg)"""
        mp = self.carried_mass
        if self.a.use_rigid_body:
            self._sync_payload()
            q, _, _ = self._q()
            M = self.model.mass_matrix(q)
            return M[0][0], M[1][1], -self.model.gravity(q)[1], mp
        a = self.a
        L = a.reach
        th = self.shoulder.theta
        # shoulder: link-1 uniform rod about its end, link-2+magnet and payload as point masses at reach
        j_sh = a.m_link1 * L * L / 3.0 + (a.m_link2 + mp) * L * L
        t_g = G * math.sin(th) * (a.m_link1 * L / 2.0 + (a.m_link2 + mp) * L)
        # base: same masses at horizontal radius L*sin(theta)
        r = L * math.sin(th)
        j_b = a.j_base_struct + (a.m_link1 / 3.0 + a.m_link2 + mp) * r * r
        return j_b, j_sh, t_g, mp

    def _rigid_external(self, dt: float):
        """(J_b, J_s, t_ext_b, t_ext_s) from the rigid-body model, refreshed once per PLC scan."""
        self.sim_t += dt
        if self._cache is None or self.sim_t - self._cache_t >= 0.005:
            for i, ax in enumerate((self.base, self.shoulder)):
                self._alpha_f[i] += 0.1 * (ax.alpha - self._alpha_f[i])
            self._sync_payload()
            q, qd, qdd = self._q()
            J, t = self.model.external_torques(q, qd, qdd)
            self._cache, self._cache_t = (J[0], J[1], t[0], t[1]), self.sim_t
        return self._cache

    def step(self, dt: float, magnet_on: bool) -> None:
        if self.a.use_rigid_body:
            j_b, j_s, t_b, t_s = self._rigid_external(dt)
        else:
            j_b, j_s, t_s, _ = self.loads()
            t_b = 0.0
        self.base.step(dt, j_b, t_b)
        self.shoulder.step(dt, j_s, t_s)
        self._part_logic(magnet_on)

    def structural_state(self) -> dict:
        """Stress / deformation / FOS estimate at the current state (see twin/loads.py)."""
        self._sync_payload()
        for i, ax in enumerate((self.base, self.shoulder)):
            if not self.a.use_rigid_body:
                self._alpha_f[i] += 0.1 * (ax.alpha - self._alpha_f[i])
        q, qd, qdd = self._q()
        return self.structural.evaluate(q, qd, qdd)

    # --- part handling ---------------------------------------------------
    def set_pick_site(self, pos: list[float]) -> None:
        self.pick_site = [pos[0], pos[1], self.a.part_height / 2]
        if self.part is None:
            self.spawn_part()

    def spawn_part(self) -> None:
        if self.pick_site:
            self.part = Part(list(self.pick_site), "free", self.a.payload)
            self.events.append("part supplied at pick point")

    def _part_logic(self, magnet_on: bool) -> None:
        a, p = self.a, self.part
        tip = self.tip()
        if p is None:
            if a.feeder and self.pick_site and math.dist(tip[:2], self.pick_site[:2]) > 0.15:
                self.spawn_part()
            return
        if p.state == "free" and magnet_on:
            d = math.dist(tip, [p.pos[0], p.pos[1], p.pos[2] + a.part_height / 2])
            if d < a.magnet_range:
                p.state = "carried"
                self.picks += 1
                self.events.append(f"magnet captured {p.mass:.1f} kg part")
        if p.state == "carried":
            if magnet_on:
                p.pos = [tip[0], tip[1], tip[2] - a.part_height / 2]
            else:
                drop_h = p.pos[2] - a.part_height / 2
                p.pos[2] = a.part_height / 2
                p.state = "placed"
                self.events.append(f"magnet released, part dropped {drop_h * 1000:.0f} mm")
                self.drops += 1
                self.placed = p
                self.part = None

    def reset_pose(self) -> None:
        self.base = Axis(self.cfg.base, 0.0)
        self.shoulder = Axis(self.cfg.shoulder, 0.0)
